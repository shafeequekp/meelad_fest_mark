# Meelad Fest Mark

## CI/CD Integration

This project uses GitHub Actions and Docker for Continuous Integration and Continuous Deployment.

### Overview
- **Continuous Integration (CI)**: Runs `flake8` linting and Django tests on every push and pull request.
- **Continuous Deployment (CD)**: Builds a Docker image, pushes it to Docker Hub, and deploys it to your VPS on every push to the `main` or `master` branch.

### Files
- `Dockerfile`: Defines the Docker image.
- `.dockerignore`: Excludes unnecessary files.
- `.github/workflows/ci.yml`: CI workflow.
- `.github/workflows/cd.yml`: CD workflow.
- `meelad/production.py`: Database configuration via environment variables.

### Setup Required
To make the CD pipeline work, add the following **Secrets** to your GitHub repository under **Settings > Secrets and variables > Actions**:

| Secret Name | Description |
| :--- | :--- |
| `DOCKER_HUB_USERNAME` | Your Docker Hub username. |
| `DOCKER_HUB_ACCESS_TOKEN` | Your Docker Hub Access Token (or password). |
| `DEPLOY_HOST` | The IP address or hostname of your VPS. |
| `DEPLOY_USER` | The username to SSH into your VPS (e.g., `ubuntu` or `root`). |
| `DEPLOY_SSH_KEY` | The private SSH key for accessing your VPS. |

> **Database Configuration**: The CD workflow connects to a MySQL database on the VPS host (`--net=host`). Ensure a database named `meelad_db` exists.

### Verification
1.  **CI**: Check the "Django CI" workflow in GitHub Actions tab.
2.  **CD**: Check the "Django CD" workflow on push to `main`.
3.  **Deployment**: Visit server IP at port 8000.

## Local Testing & Docker Usage

### Prerequisites
- Docker installed.

### Docker Installation (Linux)
If you haven't installed Docker yet, you can use the following commands:
```bash
# Uninstall old versions
sudo apt-get remove docker docker-engine docker.io containerd runc

# Set up the repository
sudo apt-get update
sudo apt-get install \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Add Docker's official GPG key
sudo mkdir -m 0755 -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Set up the repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verify installation
sudo docker run hello-world
```

### Option 1: Using Host Network (Linux Only)
Best for connecting to local MySQL:
```bash
docker build -t meelad_app .
docker run --network="host" meelad_app
```
App available at `http://localhost:8000`.

### Option 2: Standard Port Mapping
For isolated runs or other OS:
```bash
docker build -t meelad_app .
docker run -p 8000:8000 \
  -e DB_HOST=host.docker.internal \
  -e DB_USER=root \
  -e DB_PASSWORD=mind@123 \
  -e DB_NAME=meelad_db \
  --add-host=host.docker.internal:host-gateway \
  meelad_app
```




### command to run docker and stop
docker compose down && docker compose up -d --build

