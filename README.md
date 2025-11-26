# Azure AD Authentication with LangGraph + Arcade.dev Tools

This project demonstrates Azure AD (Microsoft Entra ID) authentication integration with LangGraph API, enhanced with Arcade.dev tools for OAuth-based integrations. It uses MSAL for token management and Cosmos DB for persistent token storage.

## Setup

### Environment Variables

1. Create a `.env` file based off the `.env.example` file in the repo. You will fill in these environment variables as you continue setup.

2. Begin by adding the required LangSmith variables to trace application runs to LangSmith.

3. We also use OpenAI models in this application, so add your OpenAI API Key as well.

4. Add your Arcade configuration (see Arcade.dev Configuration section below):
   - `ARCADE_API_KEY` - Your Arcade API key
   - `ARCADE_MCP_URL` - Your Arcade MCP gateway URL

5. Generate a session secret to store as `SESSION_SECRET` in your env file. You can do this in a bash terminal by running:

    ```bash
    python -c "import secrets; print(secrets.token_urlsafe(32))"
    ```

### Azure Configuration

<details>
<summary>Basics</summary>

1. First, you must get sign up for an Azure account and create a Subscription.
    - [Azure for Students](https://azure.microsoft.com/en-us/free/students) gives you credits for free if you have a school related account.
    - With an account, you should have access to Microsoft Entra ID, and a default tenant should be configured for you.
    - You also should have access to CosmosDB.

</details>

<details>
<summary>Microsoft Entra ID</summary>

1. In the Azure home page search bar, navigate to "Microsoft Entra ID". This should bring you to your default tenant.
    - Record the tenant ID, this is `AAD_TENANT_ID` in your env file

2. In the "Add" button, create a new App Registration
    - This App Registration represents your LangGraph application to Azure. By creating one, you can now let Azure know when your LangGraph application is making requests to Azure for authn/z
    - Give the App Registration any name you want, and make it multitenant
    - Provide a redirect URL for **your frontend**. By default in this repo, this value should be `http://localhost:3000/auth/callback`. However, if you host this frontend at a different URL, it should be `https://<your-domain>/auth/callback`.

3. After creating the App Registration, you should see an Overview page for your app. Note the following for your environment file:
    - Your Application (client) ID - this is `AAD_CLIENT_ID` in your env file
    - Your Application ID URI - this is `AAD_APPLICATION_URI` in your env file

4. In the left hand navigation pane for your App Registration, click "Certificates and Secrets"
    - Create a new Client secret with any name you like
    - Copy the Value - this is `AAD_CLIENT_SECRET` in your env file

5. Click "Manifest" in the left hand navigation pane for your App Registration
    - Set "accessTokenAcceptedVersion": 2
    - Save your changes. This ensures that access tokens and id tokens us the v2 issuer format: `https://login.microsoftonline.com/{tenant_id}/v2.0`
    - If you don't set this, you'll get v1 tokens with issuer `https://sts.windows.net/{tenant_id}/` which will cause authentication failures.

6. Click "API Permissions" in the left hand navigation pane for your App Registration
    - Click *Add a Permission*, select *Microsoft Graph* and *Delegated Permissions*. Add "User.Read"
    - Click *Add a Permission*, select *APIs My Organization Uses* and search for *Azure Resource Manager*
    - Select *Azure Resource Manager* and *Delegated Permissions*. Add "user_impersonation" as a permission
    - These two API permissions allow your LangGraph Application to access Microsoft resources on behalf of a user (delegated access)
    - Specifically, it allows your LangGraph Application to read the user's profile information from Microsoft Graph, and act as that user in managing Azure Resources.
    - Users need to consent before your app will be able to finalize its access - this consent process happens during your LangGraph application's runtime through a pop-up.

8. Click "Expose an API" in the left hand navigation pane for your App Registration
    - Add a scope named "access". Allow admins and users to consent.
    - The display names and descriptions can be whatever you like
    - This represents a resource that you want your LangGraph app to expose - just like how Microsoft Graph exposes user profile information
    - In this case, we are setting an arbitrary scope to represent general access to LangGraph resources (i.e. viewing threads, assistants)
    - You can add more granular scopes and use Azure AD to track which users have permission to access LangGraph resources. See `backend/auth.py:authenticate` and `backend/auth.py:add_owner`.
    - [Helpful Guides](https://langchain-ai.github.io/langgraph/tutorials/auth/resource_auth/) are available on the above process.

</details>

<details>
<summary>CosmosDB</summary>

1. In the Azure home page search bar, navigate to "Azure Cosmos DB".

2. Click "Create" and select Azure Cosmos DB for NoSQL
    - Set "Learning" Workload Type (or higher if you intend to scale)
    - Select your *Azure Subscription* and create a *Resource Group* for your project
    - Proceed with the defaults and create the Azure Cosmos DB Account. You may need to adjust location to successfully create

3. When your resource is ready, go to its Overview page
    - Note the URI - the portion before the ":" is the `COSMOS_URL` in your env file. The portion after the ":" is your `COSMOS_PORT`, and should be by default `443`

4. In the left hand navigation bar, enter the Data Explorer
    - Click *Create New Container* - this will be where your LangGraph application will store sensitive secrets and tokens
    - Create a *new Database* - the name will be `COSMOS_DB` in your env file
    - Create a *Container* - the name will be `COSMOS_CONTAINER` in your env file
    - Create a *Partition Key* - the name **without** the leading slash will be `COSMOS_PARITION_KEY` in your env file
    - Set scaling to manual to limit resource spend and create

5. A [visual reference](https://learn.microsoft.com/en-us/azure/cosmos-db/nosql/quickstart-portal) of what the CosmosDB UX may be helpful

</details>

### Arcade.dev Configuration

This application uses [Arcade.dev](https://arcade.dev) to provide OAuth-based tools for accessing external services (Notion, Google, Microsoft, Slack, etc.). Arcade provides an MCP (Model Context Protocol) gateway that exposes tools as LangChain-compatible functions, while our custom verifier ensures user-scoped OAuth security.

<details>
<summary>1. Create an Arcade Account & Get API Key</summary>

1. Sign up at [arcade.dev](https://arcade.dev)
2. Create a new project or use an existing one
3. Navigate to the [API Keys section](https://api.arcade.dev/dashboard/settings/api-keys) and create an API key
4. Add this to your `.env` file as `ARCADE_API_KEY`

</details>

<details>
<summary>2. Create an MCP Gateway</summary>

Arcade exposes tools via MCP (Model Context Protocol) servers. You need to create a gateway that bundles the tools you want to use.

1. Navigate to [MCP Gateways](https://api.arcade.dev/dashboard/mcp/gateways) in the Arcade Dashboard
2. Click **Create Gateway**
3. Select the toolkits you want to include (e.g., Notion, Google, Slack)
4. After creating the gateway, copy the **Gateway URL** - it will look like:
   ```
   https://api.arcade.dev/mcp/gw_xxxxxxxxxxxxx
   ```
5. Add this to your `.env` file as `ARCADE_MCP_URL`

**How MCP Integration Works:**

The application uses `langchain-mcp-adapters` to connect to Arcade's MCP gateway:

```python
# backend/arcade_tools.py
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "arcade": {
        "transport": "streamable_http",
        "url": ARCADE_MCP_URL,
        "headers": {
            "Authorization": f"Bearer {ARCADE_API_KEY}",
            "Arcade-User-Id": user_id,  # Scopes OAuth to authenticated user
        }
    }
})
tools = await client.get_tools()
```

The `Arcade-User-Id` header ensures that OAuth tokens are scoped per-user - each user authorizes their own access to external services.

</details>

<details>
<summary>3. Configure Custom OAuth Providers (Required for Production)</summary>

**Important:** Arcade's default OAuth apps only work with Arcade's built-in user verifier. For multi-user production apps with a custom verifier, you **must** configure your own OAuth applications.

**Example: Setting up Notion OAuth**

1. Go to [Notion Developers](https://www.notion.so/my-integrations) and create a new integration
2. Set the integration type to **Public**
3. Configure the OAuth redirect URL to Arcade's callback:
   ```
   https://cloud.arcade.dev/api/v1/oauth/callback
   ```
4. Note your **OAuth Client ID** and **OAuth Client Secret**
5. In Arcade Dashboard, navigate to [Auth > OAuth Providers](https://api.arcade.dev/dashboard/auth/providers)
6. Click **Add Provider** and select Notion
7. Enter your Client ID and Client Secret
8. Save the configuration

**Other Providers:**

Follow similar steps for other OAuth providers:
- **Google**: [Arcade's Google configuration guide](https://docs.arcade.dev/home/auth-providers/google)
- **Microsoft**: [Arcade's Microsoft configuration guide](https://docs.arcade.dev/home/auth-providers/microsoft)
- **Slack**: [Arcade's Slack configuration guide](https://docs.arcade.dev/home/auth-providers/slack)
- **Full list**: [Arcade auth providers documentation](https://docs.arcade.dev/home/auth-providers)

</details>

<details>
<summary>4. Configure Custom User Verifier</summary>

The custom user verifier is a security feature that prevents phishing attacks by confirming the user's identity during OAuth flows. When a user completes an OAuth flow, Arcade redirects them to your verifier endpoint to confirm their identity matches who initiated the flow.

**Setup Steps:**

1. Navigate to [Auth > Settings](https://api.arcade.dev/dashboard/auth/settings) in the Arcade Dashboard
2. Under **Verification Method**, select **Custom user verifier**
3. Enter your verifier URL:
   - For local development: `http://localhost:2024/arcade/verify`
   - For production: `https://your-deployment-url/arcade/verify`

**How the Verifier Works:**

The `/arcade/verify` endpoint in `backend/app.py`:
1. Receives the `flow_id` from Arcade's redirect
2. Extracts the `user_id` from the session (set during Azure AD login)
3. Calls `arcade_client.auth.confirm_user(flow_id, user_id)` to verify identity
4. Arcade completes the OAuth flow once verified

</details>

<details>
<summary>5. OAuth Flow Explained</summary>

When a user requests an action requiring OAuth (e.g., "search my Notion workspace"):

1. **Tool Detection**: The Arcade tool detects the user hasn't authorized the service
2. **Auth URL Returned**: The agent returns an authorization URL to the user
3. **User Authorizes**: User clicks the link and completes OAuth consent on the external service (e.g., Notion)
4. **Arcade Callback**: The external service redirects to Arcade's callback URL
5. **Custom Verifier**: Arcade redirects to your `/arcade/verify` endpoint with a `flow_id`
6. **Identity Confirmation**: Your verifier confirms the session `user_id` matches the flow initiator
7. **Flow Complete**: Arcade stores the OAuth token, scoped to that user
8. **Future Requests**: Subsequent tool calls automatically use the cached token

This flow ensures:
- **Security**: Only the user who initiated the flow can complete it
- **User Scoping**: Each user's OAuth tokens are isolated
- **Seamless UX**: After first authorization, tools work automatically

</details>

**Reference Documentation:**
- [Arcade Custom User Verifier](https://docs.arcade.dev/home/auth/secure-auth-production)
- [Arcade MCP Gateway](https://docs.arcade.dev/home/mcp)
- [Arcade Toolkits](https://docs.arcade.dev/toolkits)
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters)

## Architecture

This application consists of:

1. **LangGraph Server backend** with custom FastAPI routes
    - `backend/agent.py` - LangGraph agent with Arcade MCP tools (uses graph factory pattern for runtime user context)
    - `backend/arcade_tools.py` - Arcade MCP gateway integration using `langchain-mcp-adapters`
    - `backend/app.py` - FastAPI routes including Azure AD callbacks and `/arcade/verify` custom verifier
    - `backend/auth.py` - LangGraph authentication middleware using Azure AD
    - `backend/secrets.py` - Secure token storage in CosmosDB
    - `backend/tools.py` - Legacy Azure OBO tools (kept for reference)

2. **Next.js Frontend**
    - `frontend/app/auth/callback` - Redirect URI for Azure AD authorization code flow
    - `frontend/app/page.tsx` - Main application page
    - `frontend/components/Chat.tsx` - Chat component with message handling
    - `frontend/lib/auth.tsx` - Frontend authentication handlers

## Running the Application

### Using the Scripts 

Note: These scripts should be modified in production settings. They will start your application in a development environment. All scripts **MUST** be run from the root directory of this repo.

1. Install dependencies using 
    ```bash
    scripts/install.sh
    ```
2. Start the application frontend and backend using
    ```bash
    scripts/run.sh
    ```
3. A browser window should open to the frontend (default localhost:3000).
4. After finishing usage of your application, shut it down using
    ```bash
    scripts/shutdown.sh
    ``` 

### Manually Running the Application

1. In terminal, start the backend by running:

    ```bash
    langgraph dev
    ```
    in the root directory of this repo. The backend will be available at `localhost:2024`

2. In a separate terminal, start the frontend by running:

    ```bash
    npm run dev
    ```
    in the `frontend` directory of this repo. The frontend will be available at `localhost:3000`

3. Navigate to `localhost:3000` to interact with the application.

NOTE: Starting manually will show the logs in your terminals for live debugging

### Testing Arcade Tools

1. Log in with your Azure AD credentials
2. Ask the agent to perform an action requiring OAuth (e.g., "List my Notion pages")
3. The agent will return an authorization URL - click it to authorize
4. After authorization, you'll be redirected through the custom verifier
5. Return to the chat and retry your request - it should now work!
