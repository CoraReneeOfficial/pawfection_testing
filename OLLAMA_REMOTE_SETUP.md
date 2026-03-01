# Exposing Local Ollama to the Cloud

If you have deployed this application to a cloud provider like Railway but wish to run the Ollama AI model locally on your own hardware (e.g., your laptop) to save costs and utilize local memory/GPU resources, you need to expose your local Ollama server to the internet.

By default, the cloud application tries to reach Ollama at `http://localhost:11434`, which inside a cloud container refers to the container itself, not your computer.

This guide provides instructions on how to securely expose your local Ollama instance so your cloud app can communicate with it using tools like **ngrok** or **Cloudflare Tunnels**.

---

## Option 1: Using ngrok (Easiest for testing)

ngrok is a fast way to create a secure tunnel to your localhost.

### Step 1: Install ngrok
1. Go to [https://ngrok.com/](https://ngrok.com/) and create a free account.
2. Download and install ngrok for your operating system.
3. Authenticate your ngrok agent with your authtoken (found on your ngrok dashboard):
   ```bash
   ngrok config add-authtoken YOUR_AUTHTOKEN
   ```

### Step 2: Start your local Ollama server
Ensure Ollama is running and the model is downloaded:
```bash
ollama serve
# In a separate terminal, ensure the model is ready
ollama run Gemma3:12b
```

### Step 3: Start the ngrok tunnel
Run the following command in your terminal to expose port `11434` (Ollama's default port):
```bash
ngrok http 11434
```

### Step 4: Update Cloud Environment Variables
1. Look at the ngrok terminal output. You will see a "Forwarding" URL that looks like `https://1a2b-3c4d-5e6f.ngrok.app`.
2. Go to your cloud provider's dashboard (e.g., Railway).
3. Find the environment variables section for your application.
4. Set the `OLLAMA_URL` variable to your ngrok URL:
   ```env
   OLLAMA_URL=https://1a2b-3c4d-5e6f.ngrok.app
   ```
5. Restart or redeploy your cloud application.

*Note: With a free ngrok account, your URL changes every time you restart ngrok. You will need to update the `OLLAMA_URL` environment variable whenever you restart the tunnel.*

---

## Option 2: Using Cloudflare Tunnels (Best for persistence)

Cloudflare Tunnels provide a more permanent, secure, and free way to expose local services without opening firewall ports.

### Step 1: Install cloudflared
1. Create a free [Cloudflare](https://www.cloudflare.com/) account.
2. Download and install the `cloudflared` daemon for your OS from the [Cloudflare Tunnel documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-local-tunnel/).

### Step 2: Authenticate and Create a Tunnel
1. Authenticate `cloudflared`:
   ```bash
   cloudflared tunnel login
   ```
2. Create a new tunnel (e.g., name it `ollama-tunnel`):
   ```bash
   cloudflared tunnel create ollama-tunnel
   ```
3. Take note of the Tunnel UUID generated in the output.

### Step 3: Route Traffic to Ollama
Assuming you have a domain managed by Cloudflare, you can route a subdomain (e.g., `ai.yourdomain.com`) to your tunnel:
```bash
cloudflared tunnel route dns ollama-tunnel ai.yourdomain.com
```

### Step 4: Run the Tunnel
Run the tunnel, forwarding traffic to your local Ollama port:
```bash
cloudflared tunnel run --url http://localhost:11434 ollama-tunnel
```

### Step 5: Update Cloud Environment Variables
1. Go to your cloud provider's dashboard (e.g., Railway).
2. Find the environment variables section for your application.
3. Set the `OLLAMA_URL` variable to your Cloudflare Tunnel URL:
   ```env
   OLLAMA_URL=https://ai.yourdomain.com
   ```
4. Restart or redeploy your cloud application.

---

## Important Considerations

- **Security:** Exposing Ollama directly to the internet means anyone with the URL can use your local AI resources. Do not share the ngrok or Cloudflare URL publicly.
- **Uptime:** For the cloud app to use the AI, your laptop must be powered on, awake, connected to the internet, and running the tunnel software. If your laptop goes to sleep or the tunnel disconnects, the app will fall back to Gemini (if configured).
- **Environment Variable Fallback:** Ensure `GEMINI_API_KEY` is still configured in your cloud environment variables. If your local Ollama connection drops, the app will gracefully fall back to using Gemini.