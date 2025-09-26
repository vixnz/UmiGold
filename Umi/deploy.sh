#!/usr/bin/env bash

# Stop on any error
set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Build and push Docker images
docker-compose build
docker-compose push

# Deploy VS Code extension
cd ide_extension
npm install
npm run vscode:prepublish
# Package the extension
vsce package
# The .vsix file can now be published to the VS Code marketplace or installed locally

# Return to root
cd ..

# Create required directories
mkdir -p data/models
mkdir -p data/telemetry

# Initialize database
docker-compose up -d telemetry_db
# Wait for database to be ready
sleep 10

# Start all services
docker-compose up -d

echo "Deployment completed successfully!"
echo "Check the status with: docker-compose ps"