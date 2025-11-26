import os
import time
import secrets
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from backend.auth import verify_id_token, msal_app, AAD_REDIRECT_URI, AAD_APPLICATION_URI, token_cache, get_refreshed_azure_tokens, extract_info_from_cache
from backend.secrets import save_token_cache_to_cosmos, get_cosmos_container, close_cosmos_connections

# Arcade imports
from arcadepy import AsyncArcade


load_dotenv(override=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan with proper resource cleanup"""
    # Startup
    print("🚀 Starting up FastAPI application...")
    yield
    # Shutdown
    print("🛑 Shutting down FastAPI application...")
    # Close Cosmos DB connections
    await close_cosmos_connections()


app = FastAPI(lifespan=lifespan)


app.add_middleware(
    SessionMiddleware, 
    secret_key=os.environ["SESSION_SECRET"], 
    max_age=3600,
    same_site="lax",  # Changed from "none" to "lax" for better compatibility
    https_only=False,  # Allow HTTP for local development
    path="/"  # Ensure cookie is set for all paths
)
# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


NECESSARY_AAD_SCOPES = [
    "email", # built in openid scope
    f"{AAD_APPLICATION_URI}/access", # access to our LangGraph app
]

@app.get("/")
async def root(request: Request):
    """Root endpoint"""
    return {"message": "Application is running."}


@app.get("/auth/login")
async def login(request: Request):
    """Start the Azure AD login flow - returns redirect URL"""
    state = secrets.token_urlsafe(16)
    request.session["state"] = state # To prevent CSRF attacks
    # TODO: Use check the state in the callback, and if it's not the same, return an error
    # Create the authorization URL
    auth_url = msal_app.get_authorization_request_url(
        scopes=NECESSARY_AAD_SCOPES,
        redirect_uri=AAD_REDIRECT_URI,
        state=state,
        prompt="select_account"
    )
    return JSONResponse({"auth_url": auth_url})


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """
    Handle the Azure AD callback after user login.
    Accepts an optional 'scopes' query parameter, falls back to empty scopes.
    """
    # Get code and state from query parameters
    code = request.query_params.get("code")
    scopes_param = request.query_params.get("scopes")
    # TODO: Can check state here for CSRF attacks
    scopes = []
    if scopes_param:
        scopes = [s.strip() for s in scopes_param.split() if s.strip()]  
    if not code:
        return Response("No authorization code provided", status_code=400)
    # Exchange code for token
    try:
        # Wrap the blocking MSAL call in asyncio.to_thread
        result = await asyncio.to_thread(
            msal_app.acquire_token_by_authorization_code,
            code, scopes=scopes,
            redirect_uri=AAD_REDIRECT_URI,
        )
        if "access_token" in result and "id_token" in result:
            id_token = result["id_token"]
            # Verify id_token signature and claims
            try:
                id_claims = await verify_id_token(id_token)
                oid = id_claims.get("oid")
                tid = id_claims.get("tid")
            except Exception as e:
                return Response("❌ Auth Callback Error:Failed to verify id_token", status_code=400)
            if not oid or not tid:
                return Response("❌ Auth Callback Error: Missing 'oid' or 'tid' claim in id_token", status_code=400)
            # Save the MSAL token cache to Cosmos DB using the user's oid.tid as the key
            cosmos_container = await get_cosmos_container()
            user_key = f"{oid}.{tid}"
            await save_token_cache_to_cosmos(token_cache, cosmos_container, user_key)
            # Store tokens in session for client access
            request.session["user_id"] = user_key
            request.session["auth_time"] = time.time()  # Add session timestamp
            request.session["user_email"] = id_claims.get("email", "")
            request.session["user_name"] = id_claims.get("name", "")
            # Redirect back to the frontend after successful authentication
            return Response(status_code=200)
        else:
            error_msg = result.get("error_description", "Unknown error")
            return Response(f"❌ Auth Callback Error: {error_msg}", status_code=400)
    except Exception as e:
        return Response("❌ Auth Callback Error: Token exchange failed raising " + str(e), status_code=400)


@app.get("/auth/status")
async def auth_status(request: Request):
    """Check if user is authenticated"""
    access_token = request.session.get("access_token")
    if access_token:
        return JSONResponse({"authenticated": True})
    else:
        return JSONResponse({"authenticated": False})


@app.get("/auth/logout")
async def logout(request: Request):
    """Clear session and redirect to home"""
    request.session.clear()
    return Response(status_code=200)


@app.get("/auth/tokens")
async def get_tokens(request: Request):
    """Get access and id tokens for the authenticated user"""
    user_id = request.session.get("user_id") 
    if not user_id:
        return JSONResponse({"error": "❌ Token Issuance Error: No valid session"}, status_code=401)
    
    try:
        # Use existing helper to get fresh tokens from Cosmos DB cache
        cosmos_container = await get_cosmos_container()
        token_info = await extract_info_from_cache(user_id, cosmos_container)
        
        if not token_info:
            return JSONResponse({"error": "❌ Token Issuance Error: No token info found in cache"}, status_code=401)
        
        # Use existing helper to get a valid access token (handles refresh automatically)
        access_token, id_token = await get_refreshed_azure_tokens(token_info, NECESSARY_AAD_SCOPES)
        return JSONResponse({
            "access_token": access_token,
            "id_token": id_token
        })
        
    except Exception as e:
        return JSONResponse({"error": f"❌ Token Issuance Error: {str(e)}"}, status_code=401)


@app.get("/arcade/verify")
async def arcade_verify(request: Request, flow_id: str):
    """
    Arcade custom user verifier endpoint.
    
    This endpoint is called by Arcade after a user completes an OAuth flow.
    It verifies that the user who completed the OAuth flow is the same user
    who initiated it, preventing phishing attacks.
    
    Reference: https://docs.arcade.dev/home/auth/secure-auth-production
    
    Args:
        flow_id: The OAuth flow ID from Arcade (query parameter)
    
    Returns:
        Redirect to Arcade's next_uri or success page
    """
    # Validate required parameters
    if not flow_id:
        return Response("❌ Arcade Verify Error: Missing required parameter: flow_id", status_code=400)
    
    # Extract user_id from session (established during Azure AD login)
    # This must match the user_id that was passed when the Arcade tool was called
    user_id = request.session.get("user_id")
    
    if not user_id:
        return Response(
            "❌ Arcade Verify Error: User not authenticated. Please log in first.",
            status_code=401
        )
    
    # Confirm the user's identity with Arcade (server-side, uses ARCADE_API_KEY)
    try:
        client = AsyncArcade()  # Looks for ARCADE_API_KEY environment variable
        
        result = await client.auth.confirm_user(
            flow_id=flow_id,
            user_id=user_id
        )
        
        # Wait for the authorization to complete and verify status
        auth_response = await client.auth.wait_for_completion(result.auth_id)
        
        if auth_response.status == "completed":
            # Success! Redirect to Arcade's next step or render success page
            # You can customize this to redirect to your frontend or show a success message
            from fastapi.responses import RedirectResponse, HTMLResponse
            
            # Option 1: Redirect to Arcade's next_uri (recommended)
            if result.next_uri:
                return RedirectResponse(url=result.next_uri)
            
            # Option 2: Show a simple success page
            return HTMLResponse(
                content="""
                <html>
                    <head>
                        <title>Authorization Successful</title>
                        <style>
                            body {
                                font-family: system-ui, -apple-system, sans-serif;
                                display: flex;
                                justify-content: center;
                                align-items: center;
                                height: 100vh;
                                margin: 0;
                                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            }
                            .card {
                                background: white;
                                padding: 2rem;
                                border-radius: 8px;
                                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                                text-align: center;
                                max-width: 400px;
                            }
                            h1 { color: #10b981; margin-top: 0; }
                            p { color: #6b7280; }
                            .close-btn {
                                margin-top: 1rem;
                                padding: 0.5rem 1rem;
                                background: #667eea;
                                color: white;
                                border: none;
                                border-radius: 4px;
                                cursor: pointer;
                            }
                        </style>
                    </head>
                    <body>
                        <div class="card">
                            <h1>✓ Authorization Successful</h1>
                            <p>You have successfully authorized the application.</p>
                            <p>You can close this window and return to the application.</p>
                            <button class="close-btn" onclick="window.close()">Close Window</button>
                        </div>
                    </body>
                </html>
                """,
                status_code=200
            )
        else:
            # Authorization did not complete successfully
            return Response(
                f"❌ Arcade Verify Error: Authorization status: {auth_response.status}",
                status_code=400
            )
            
    except Exception as e:
        # Log the error for debugging
        print(f"❌ Arcade Verify Error: {str(e)}")
        return Response(
            f"❌ Arcade Verify Error: Failed to verify user. {str(e)}",
            status_code=400
        )
