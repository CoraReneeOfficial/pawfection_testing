# Ollama AI Assistant Setup Guide

This guide walks you through setting up Ollama locally and configuring it to be the primary AI engine for the application, using the `llama3.1:8b` model.

## Prerequisites
- A machine capable of running local AI models (8GB+ RAM recommended for `llama3.1:8b`).

## Step 1: Install Ollama

Ollama allows you to run large language models locally.

### On macOS
Download and install the macOS application from the official site:
[https://ollama.com/download/mac](https://ollama.com/download/mac)

### On Windows
Download and install the Windows preview from the official site:
[https://ollama.com/download/windows](https://ollama.com/download/windows)

### On Linux
Run the following install script in your terminal:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

## Step 2: Download the Llama 3.1 8b Model

Once Ollama is installed and running, open your terminal or command prompt. You need to pull the `llama3.1:8b` model, which supports the native tool-calling features required by this application.

Run the following command:
```bash
ollama run llama3.1:8b
```

- This will download the model (it may take some time depending on your internet connection).
- Once downloaded, it will start an interactive prompt. You can type `/bye` to exit the prompt. The model is now ready to be used by the application.

## Step 3: Verify Ollama is Running

Ollama runs a local API server on port `11434` by default. You can verify it's running by opening your web browser and navigating to your configured ngrok URL, for example:

[https://erlene-nonadaptational-elden.ngrok-free.dev](https://erlene-nonadaptational-elden.ngrok-free.dev)

You should see a message saying "Ollama is running".

## Step 4: Application Configuration

The application is now configured to attempt connection to Ollama first.

- **Primary AI**: The application will automatically try to connect to the configured URL (defaulting to `https://erlene-nonadaptational-elden.ngrok-free.dev`) and use the configured model (defaulting to `llama3.1:8b`).
- **Fallback**: If Ollama is turned off, offline, or unavailable, the application will automatically fall back to using Google Gemini (via the `GEMINI_API_KEY` defined in your `.env` file).

**Configuring Custom Ollama Host or Model**
If you wish to use a different Ollama host URL or a different model, you can set the following environment variables in your `.env` file:
```env
OLLAMA_URL=https://erlene-nonadaptational-elden.ngrok-free.dev
OLLAMA_MODEL=llama3.1:8b
```
Ensure your `GEMINI_API_KEY` is still configured so the fallback works if needed!

---
**Troubleshooting Tool Calling:**
If the AI is not responding correctly to booking requests or looking up data, ensure you are specifically using a model with native tool-calling capabilities (like `llama3.1:8b` or newer Llama models). You can check your installed models by running `ollama list` in your terminal.