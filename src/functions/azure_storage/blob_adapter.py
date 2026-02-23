"""Azure Blob Storage adapter for storing and retrieving scraped data."""

import json
import os
from datetime import datetime
from typing import Optional, List
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
from utils.logger import Logger


class AzureBlobStorageAdapter:
    """Adapter for interacting with Azure Blob Storage."""

    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize the Azure Blob Storage adapter.

        Args:
            connection_string: Azure Storage connection string.
                             If not provided, uses DefaultAzureCredential.
        """
        self.logger = Logger()

        if connection_string:
            self.blob_service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
        else:
            # Use managed identity for authentication
            account_url = f"https://{os.getenv('AZURE_STORAGE_ACCOUNT_NAME')}.blob.core.windows.net"
            credential = DefaultAzureCredential()
            self.blob_service_client = BlobServiceClient(
                account_url=account_url, credential=credential
            )

        self.container_name = os.getenv("BLOB_CONTAINER_NAME", "scraped-data")
        self.logger.log_info(
            f"Azure Blob Storage adapter initialized for container: {self.container_name}"
        )

    def save_data(self, data: dict, blob_name: Optional[str] = None) -> str:
        """
        Save data to Azure Blob Storage.

        Args:
            data: Dictionary containing the data to save
            blob_name: Optional custom blob name. If not provided, uses timestamp.

        Returns:
            The blob name/path where data was saved
        """
        try:
            if blob_name is None:
                timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
                blob_name = f"scraped_data_{timestamp}.json"

            container_client = self.blob_service_client.get_container_client(
                self.container_name
            )

            # Convert data to JSON
            json_data = json.dumps(data, ensure_ascii=False, indent=2)

            # Upload to blob storage
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(json_data, overwrite=True)

            self.logger.log_info(f"Data saved to blob: {blob_name}")
            return blob_name

        except Exception as e:
            self.logger.log_error(f"Error saving data to blob storage: {e}")
            raise

    def retrieve_data(self, blob_name: str) -> dict:
        """
        Retrieve data from Azure Blob Storage.

        Args:
            blob_name: Name of the blob to retrieve

        Returns:
            Dictionary containing the retrieved data
        """
        try:
            container_client = self.blob_service_client.get_container_client(
                self.container_name
            )
            blob_client = container_client.get_blob_client(blob_name)

            download_stream = blob_client.download_blob()
            json_data = download_stream.readall().decode("utf-8")
            data = json.loads(json_data)

            self.logger.log_info(f"Data retrieved from blob: {blob_name}")
            return data

        except Exception as e:
            self.logger.log_error(f"Error retrieving data from blob storage: {e}")
            raise

    def list_blobs(self, prefix: str = "") -> List[str]:
        """
        List all blobs in the container.

        Args:
            prefix: Optional prefix to filter blobs

        Returns:
            List of blob names
        """
        try:
            container_client = self.blob_service_client.get_container_client(
                self.container_name
            )
            blobs = container_client.list_blobs(name_starts_with=prefix)
            blob_list = [blob.name for blob in blobs]

            self.logger.log_info(f"Listed {len(blob_list)} blobs with prefix: {prefix}")
            return blob_list

        except Exception as e:
            self.logger.log_error(f"Error listing blobs: {e}")
            raise

    def get_latest_data(self) -> Optional[dict]:
        """
        Retrieve the most recently saved data.

        Returns:
            Dictionary containing the latest data, or None if no data exists
        """
        try:
            blobs = self.list_blobs(prefix="scraped_data_")
            if not blobs:
                self.logger.log_info("No scraped data found in blob storage")
                return None

            # Sort by name to get the most recent (names are timestamp-based)
            latest_blob = sorted(blobs)[-1]
            return self.retrieve_data(latest_blob)

        except Exception as e:
            self.logger.log_error(f"Error retrieving latest data: {e}")
            raise

    def delete_blob(self, blob_name: str) -> None:
        """
        Delete a blob from storage.

        Args:
            blob_name: Name of the blob to delete
        """
        try:
            container_client = self.blob_service_client.get_container_client(
                self.container_name
            )
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.delete_blob()

            self.logger.log_info(f"Blob deleted: {blob_name}")

        except Exception as e:
            self.logger.log_error(f"Error deleting blob: {e}")
            raise
