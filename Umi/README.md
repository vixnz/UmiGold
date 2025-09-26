# Umi Code Assistant

Umi is an adaptive code assistant that learns from user preferences and provides personalized code suggestions. It consists of multiple components that work together to provide a seamless development experience.

## Components

### 1. Adaptation Engine
- Learns and adapts to user's coding style preferences
- Manages style rules and user profiles
- Integrates with telemetry database for tracking user preferences

### 2. AI Engine
- Analyzes code context and patterns
- Optimizes refactoring suggestions
- Includes security scanning capabilities

### 3. Cloud Integration
- Handles analytics and telemetry data
- Provides cloud storage integration
- Supports multiple cloud providers (AWS, GCP, Azure)

### 4. Core Engine
- Manages feedback loop training
- Handles suggestion pipeline
- Coordinates between different components

### 5. IDE Extension
- VS Code extension for direct user interaction
- Provides code suggestions and adaptations
- Configurable through VS Code settings

## Setup Instructions

1. Install Dependencies:
   ```bash
   # Install Python dependencies
   pip install -r requirements.txt

   # Install VS Code extension dependencies
   cd ide_extension
   npm install
   ```

2. Configure Environment:
   - Copy `.env.example` to `.env` and fill in required values
   - Configure database settings in `docker-compose.yml`

3. Start Services:
   ```bash
   docker-compose up -d
   ```

4. Build VS Code Extension:
   ```bash
   cd ide_extension
   npm run compile
   ```

## Development

### Docker Services
- Each component runs in its own container
- Postgres database for telemetry data
- Shared volumes for development

### Python Environment
- Python 3.9+ required
- Virtual environment recommended
- Code formatting with Black
- Linting with Flake8

### VS Code Extension
- TypeScript-based
- Webpack bundling
- ESLint for linting

## Configuration

### Style Adaptation
- Configurable through `.editorconfig`
- Supports multiple programming languages
- Learns from user interactions

### VS Code Settings
- `umi.telemetryEnabled`: Enable/disable telemetry
- `umi.codeStyle`: Custom style preferences

## Contributing

1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## Deployment

### Prerequisites
- Docker and Docker Compose installed
- Node.js 16+ and npm installed
- VS Code for extension deployment
- Access to cloud services (AWS, GCP, or Azure)

### Environment Setup
1. Choose deployment environment:
   ```bash
   # For staging
   cp .env.staging .env
   # For production
   cp .env.production .env
   ```

2. Set required environment variables:
   - Database credentials
   - Cloud service credentials
   - Security keys and secrets

### Automated Deployment
1. Make the deployment script executable:
   ```bash
   chmod +x deploy.sh
   ```

2. Run the deployment:
   ```bash
   ./deploy.sh
   ```

### Manual Deployment Steps
1. Build and push Docker images:
   ```bash
   docker-compose build
   docker-compose push
   ```

2. Deploy VS Code extension:
   ```bash
   cd ide_extension
   npm install
   npm run vscode:prepublish
   vsce package
   ```
   - Publish the generated .vsix file to VS Code marketplace or
   - Install locally using `code --install-extension umi-code-x.x.x.vsix`

3. Initialize infrastructure:
   ```bash
   mkdir -p data/models data/telemetry
   ```

4. Start services:
   ```bash
   docker-compose up -d
   ```

### Monitoring
- Check service status: `docker-compose ps`
- View logs: `docker-compose logs -f [service_name]`
- Monitor database: Connect to PostgreSQL on port 5432

### Backup and Recovery
1. Database backup:
   ```bash
   docker-compose exec telemetry_db pg_dump -U umi telemetry > backup.sql
   ```

2. Restore from backup:
   ```bash
   docker-compose exec -T telemetry_db psql -U umi telemetry < backup.sql
   ```

## License

MIT License - See LICENSE file for details