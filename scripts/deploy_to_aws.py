import boto3
import zipfile
import os
import time
import sys
from datetime import datetime

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
)

s3 = session.client('s3')
eb = session.client('elasticbeanstalk')

BUCKET_NAME = 'proofsy-certificates-454708369270'
APPLICATION_NAME = 'Proofsy'
ENVIRONMENT_NAME = 'Proofsy-env'

def create_zip(zip_path):
    print("Creating source bundle ZIP...")
    exclude_dirs = {'.git', '.venv', '__pycache__', 'uploads', '.continue', '.vscode'}
    exclude_files = {'docker-compose.yml', 'render.yaml', 'deploy_to_aws.py'}
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            # Prune excluded directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                if file in exclude_files or file.endswith('.pyc') or file.endswith('.zip'):
                    continue
                
                file_path = os.path.join(root, file)
                # Strip leading './' if present
                arcname = os.path.relpath(file_path, '.')
                print(f"Adding: {arcname}")
                zipf.write(file_path, arcname)
    print(f"Source bundle created: {zip_path}")

def upload_to_s3(zip_path, s3_key):
    print(f"Uploading {zip_path} to S3 bucket {BUCKET_NAME} with key {s3_key}...")
    s3.upload_file(zip_path, BUCKET_NAME, s3_key)
    print("Upload completed successfully.")

def deploy_to_eb(s3_key, version_label):
    print(f"Creating new application version: {version_label}...")
    eb.create_application_version(
        ApplicationName=APPLICATION_NAME,
        VersionLabel=version_label,
        SourceBundle={
            'S3Bucket': BUCKET_NAME,
            'S3Key': s3_key
        },
        AutoCreateApplication=False,
        Description=f"snist_helpdesk Flask app deploy at {datetime.now().isoformat()}"
    )
    
    print(f"Updating environment {ENVIRONMENT_NAME} to version {version_label}...")
    eb.update_environment(
        EnvironmentName=ENVIRONMENT_NAME,
        VersionLabel=version_label
    )
    print("Deployment request submitted successfully.")

def monitor_deployment(version_label):
    print("Monitoring environment status...")
    start_time = time.time()
    seen_events = set()
    
    while True:
        # Check environment status
        resp = eb.describe_environments(EnvironmentNames=[ENVIRONMENT_NAME])
        if not resp['Environments']:
            print("Environment not found!")
            sys.exit(1)
            
        env = resp['Environments'][0]
        status = env['Status']
        health = env['Health']
        current_version = env.get('VersionLabel')
        
        # Fetch and print new events
        events_resp = eb.describe_events(
            EnvironmentName=ENVIRONMENT_NAME,
            StartTime=datetime.fromtimestamp(start_time - 300)
        )
        for event in reversed(events_resp.get('Events', [])):
            event_id = event.get('EventDate').isoformat() + ":" + event.get('Message')
            if event_id not in seen_events:
                seen_events.add(event_id)
                print(f"[{event.get('EventDate').strftime('%Y-%m-%d %H:%M:%S')}] [{event.get('Severity')}] {event.get('Message')}")
                
        print(f"Status: {status} | Health: {health} | Version: {current_version}")
        
        if status == 'Ready':
            if current_version == version_label:
                if health == 'Green':
                    print("Deployment successful! Environment is Ready and Health is Green.")
                    break
                elif health in ('Red', 'Degraded', 'Severe'):
                    print(f"Deployment finished, but health is critical: {health}.")
                    sys.exit(1)
            elif current_version != version_label and time.time() - start_time > 60:
                # If it went back to Ready but version didn't update, it might have rolled back or failed
                print(f"Warning: Environment returned to Ready, but version is {current_version} (expected {version_label}).")
                sys.exit(1)
                
        if time.time() - start_time > 900:  # 15 minutes timeout
            print("Deployment timeout reached.")
            sys.exit(1)
            
        time.sleep(15)

def main():
    timestamp = int(time.time())
    zip_path = f"snist-helpdesk-deploy-{timestamp}.zip"
    s3_key = f"snist-helpdesk-deploy-{timestamp}.zip"
    version_label = f"helpdesk-{timestamp}"
    
    try:
        create_zip(zip_path)
        upload_to_s3(zip_path, s3_key)
        deploy_to_eb(s3_key, version_label)
        monitor_deployment(version_label)
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
            print("Removed local zip file.")

if __name__ == '__main__':
    main()
