"""
Test function to verify blob storage connection is working.
This helps diagnose if the function app can write to Azure Storage.
"""

import azure.functions as func
import json
import os
from datetime import datetime
from azure.storage.blob import BlobClient


def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    Test endpoint that writes a test blob to verify connectivity.
    """
    try:
        # Get connection string
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            return func.HttpResponse(
                json.dumps({"error": "AZURE_STORAGE_CONNECTION_STRING not configured"}),
                status_code=500,
                mimetype="application/json"
            )
        
        # Create test blob
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        blob_name = f"test/test_write_{timestamp}.json"
        
        test_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "test": "blob_write_verification",
            "status": "success"
        }
        
        # Write to blob
        blob_client = BlobClient.from_connection_string(
            connection_string,
            container_name="scraped-data",
            blob_name=blob_name
        )
        blob_client.upload_blob(json.dumps(test_data), overwrite=True)
        
        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "message": "Test blob written successfully",
                "blob_name": blob_name,
                "container": "scraped-data"
            }),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            mimetype="application/json"
        )
