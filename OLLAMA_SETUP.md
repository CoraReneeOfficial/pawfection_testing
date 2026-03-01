# Ollama AI Assistant Setup Guide

This guide walks you through setting up Ollama locally and configuring it to be the primary AI engine for the application, using the `llama3.3` model.

## Prerequisites
- A machine capable of running local AI models (16GB+ RAM recommended for `llama3.3`).

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

## Step 2: Download the Llama 3.3 Model

Once Ollama is installed and running, open your terminal or command prompt. You need to pull the `llama3.3` model, which supports the native tool-calling features required by this application.

Run the following command:
```bash
ollama run llama3.3
```

- This will download the model (it may take some time depending on your internet connection).
- Once downloaded, it will start an interactive prompt. You can type `/bye` to exit the prompt. The model is now ready to be used by the application.

## Step 3: Verify Ollama is Running

Ollama runs a local API server on port `11434` by default. You can verify it's running by opening your web browser and navigating to:

[http://localhost:11434](http://localhost:11434)

You should see a message saying "Ollama is running".

## Step 4: Application Configuration

The application is now configured to attempt connection to Ollama first.

- **Primary AI**: The application will automatically try to connect to `http://localhost:11434` and use the `llama3.3` model.
- **Fallback**: If Ollama is turned off, offline, or unavailable, the application will automatically fall back to using Google Gemini (via the `GEMINI_API_KEY` defined in your `.env` file).

**No additional `.env` variables are required for standard local setup**, but you must ensure your `GEMINI_API_KEY` is still configured so the fallback works if needed!

---
**Troubleshooting Tool Calling:**
If the AI is not responding correctly to booking requests or looking up data, ensure you are specifically using `llama3.3` or newer (like `llama3.1` or `llama3.2`), as older standard Llama 3 models lack robust native tool-calling capabilities. You can check your installed models by running `ollama list` in your terminal.