# GenAI Agents empowering customers with transparent, tailored banking guidance
Canada DevOps Community of Practice Hackathon Toronto - Team 5 

Project Name - GenAI Agents empowering customers with transparent, tailored banking guidance

Team Mentor -

Participant Names - 
     Team Leaders - Path Parab
     
     Team Members - Daniel Nguyen, Kacper Burza, Anthony Spiteri, Onimisi Ayira

---

## Running the Application with Docker

This application uses Docker Compose to orchestrate multiple services. Here's how to run it:

### Prerequisites

- Docker and Docker Compose installed on your system
- At least 8GB of available RAM (recommended for Ollama)

### Quick Start

1. **Build and start all services:**
   ```bash
   docker-compose up --build
   ```

   This will:
   - Build all service images
   - Start all containers (Ollama, Redis, Gateway, Agents, etc.)
   - Expose the Gateway API on port 8000
   - Expose RQ Dashboard on port 9181

2. **Start services in detached mode (background):**
   ```bash
   docker-compose up -d --build
   ```

3. **View logs:**
   ```bash
   # All services
   docker-compose logs -f
   
   # Specific service
   docker-compose logs -f gateway
   ```

4. **Stop all services:**
   ```bash
   docker-compose down
   ```

### Services

The application consists of the following services:

- **ollama** (port 11434): LLM service for AI agents
- **redis** (port 6379): Job queue and message broker
- **rq-dashboard** (port 9181): Monitor job queues at http://localhost:9181
- **gateway** (port 8000): Main API gateway - http://localhost:8000
- **gateway_worker**: Background worker for processing jobs
- **orchestrator**: Coordinates agent workflows
- **conversation**: Conversation agent (2 replicas)
- **kyc**: KYC verification agent (2 replicas)
- **advisor**: Financial advisor agent (2 replicas)
- **audit**: Audit logging agent (1 replica)

### First-Time Setup

After starting Ollama, you'll need to pull a model. Run:

```bash
docker exec -it <ollama-container-name> ollama pull llama2
```

Or connect to the Ollama service and pull the model you need.

### Running the Frontend

The frontend is a Streamlit application that runs separately:

```bash
cd frontend
pip install -r requirements.txt
streamlit run app.py
```

The frontend will be available at http://localhost:8501

### Volumes

The following volumes are created for data persistence:

- `ollama`: Stores Ollama models and data
- `uploads`: Shared storage for uploaded documents (KYC)
- `audit_logs`: Persists audit logs

### Environment Variables

Most services use default Redis and Ollama URLs configured in docker-compose.yml. You can override them by setting environment variables:

- `REDIS_URL`: Redis connection URL (default: `redis://redis:6379/0`)
- `OLLAMA_URL`: Ollama service URL (default: `http://ollama:11434`)

### Troubleshooting

- **Check service status:**
  ```bash
  docker-compose ps
  ```

- **Restart a specific service:**
  ```bash
  docker-compose restart gateway
  ```

- **Rebuild after code changes:**
  ```bash
  docker-compose up --build
  ```

- **Clean up and start fresh:**
  ```bash
  docker-compose down -v  # Removes volumes too
  docker-compose up --build
  ```

