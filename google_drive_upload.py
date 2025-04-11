#! /usr/bin/env python
import os
import sys
import mimetypes
import argparse
import logging

# For some nicer type hinting
from typing import List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Set up logging
logger = logging.getLogger(__name__)

# If modifying these scopes, delete the file token.json.
SCOPES = [
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly"
]

# AUTH_TOKEN_LOCATION = os.path.expanduser("~/.owi/google_drive_uploader/token.json")
AUTH_TOKEN_LOCATION = os.path.expanduser("token.json")


# Folders in Google Drive have a special MIME type
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

# Magic string which can be used in and ID field to refer to the root
DRIVE_ROOT_FOLDER_NAME = "root"
ROOT_FOLDER_INFO = {"name": "root", "id": "root", "parent": "root", "type": FOLDER_MIME_TYPE}

### Google API utility methods

def get_google_credentials() -> Credentials:
    """Gets the user's Google credentials for use in the script.
    If there are no credentials stored at AUTH_TOKEN_LOCATION, or if they're expired, runs the user
    through the authentication process.

    Lovingly adapted from Google's Python Google Drive quickstart: https://developers.google.com/workspace/drive/api/quickstart/python

    Returns:
        google.oauth2.credentials.Credentials: The retrieved credentials.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(AUTH_TOKEN_LOCATION):
        creds = Credentials.from_authorized_user_file(AUTH_TOKEN_LOCATION, SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port = 0)
        # Save the credentials for the next run
        with open(AUTH_TOKEN_LOCATION, "w") as token:
            token.write(creds.to_json())
    return creds

def list_drive_files(google_drive_client, query: List[str], fields: List[str], drive_id = False) -> List[dict]:
    joined_query = ' and '.join(query)
    joined_fields = ', '.join(["nextPageToken"] + fields)

    list_files_args = {
        "q": joined_query,
        "spaces": "drive",
        "fields": joined_fields
    }

    if drive_id:
        list_files_args["corpora"] = "drive"
        list_files_args["supportsAllDrives"] = True
        list_files_args["driveId"] = drive_id

    logger.debug("(list_drive_files) Invoking Drive API")
    logger.debug("    query: %s", joined_query)
    logger.debug("    fields: %s", joined_fields)

    page_token = None

    files = []
    while True:
        response = (
            google_drive_client.files().list(**list_files_args, pageToken = page_token).execute()
        )

        logger.debug("(list_drive_files) response from Google API:")
        logger.debug("    %s\n", response)

        # I'm going to be honest: I'm still not sure why the second argument for extend() is an empty list.
        # I don't think it's a type hint, because surely they'd write the library to accept something like `list`,
        # instead of a reference object which it then calls .__class__ or something, right?
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken", None)
        if page_token is None:
            break
    return files

def get_drive_id(google_drive_client, drive_name: str):
    query = f"name = '{escape_google_api_query_string(drive_name)}'"

    page_token = None

    logger.debug("(get_drive_id) Invoking Drive API")
    logger.debug("    query: %s\n", query)

    response = google_drive_client.drives().list(
        q = query,
        pageToken = page_token,
    ).execute()

    logger.debug("(get_drive_id) response from Google API:")
    logger.debug("    %s\n", response)
    logger.debug("    %s\n", response.get("drives", []))

    index_to_use = 0

    if not response["drives"]:
        logger.fatal("No Drives were found with the name '%s'!", drive_name)
        sys.exit(1)

    # This will PROBABLY never happen, but let's be really safe
    if len(response["drives"]) > 1:
        logger.warning("Got more than one result while getting the id of the shared Drive '%s'! Which one should be used?", drive_name)
        for index, drive in enumerate(response["drives"]):
            print(f"{index}: {drive["name"]} (id: {drive["id"]})")

            index_to_use = input("Please type the number corresponding to the drive you want to use for this command: ")

    try:
        return response["drives"][index_to_use]["id"]
    except:
        logger.fatal("Given value '%s' was not a valid option for choosing a Drive!", index_to_use)
        sys.exit(1)

def escape_google_api_query_string(string: str) -> str:
    return string.replace("\\", "\\\\").replace("'", "\'")

### Methods that take actions

def create_drive_folder(google_drive_client, parent_id: str, name: str, drive_id: str = False) -> str:
    metadata = {
        "name": escape_google_api_query_string(name),
        "mimeType": FOLDER_MIME_TYPE,
        "parents": [parent_id]
    }

    create_args = {
        "body": metadata,
        "fields": "id"
    }

    if drive_id:
        create_args["supportsAllDrives"] = True

    logger.debug("(create_drive_folder) Invoking Drive API")
    logger.debug("    body: %s\n", create_args)

    response = google_drive_client.files().create(**create_args).execute()

    logger.debug("(create_drive_folder) response from Google API:")
    logger.debug("    %s\n", response)

    folder_id = response.get("id")

    logger.debug("(create_drive_folder) Created new folder %s with id %s\n", metadata["name"], folder_id)

    return folder_id

def create_missing_drive_folders(google_drive_client, parent: str, folders_to_make: List[str], drive_id = False) -> dict:
    """Recursively create folders, returning the details of the final folder in the list.

    Returns:
        dict: A dictionary containing the `name`, `file_id`, `parent`, and `type` of the folder.
    """
    folder_name = folders_to_make.pop(0)
    folder_id = create_drive_folder(
        google_drive_client = google_drive_client,
        parent_id = parent,
        name = folder_name,
        drive_id = drive_id
    )

    if folders_to_make:
        return create_missing_drive_folders(
            google_drive_client = google_drive_client,
            parent = folder_id,
            folders_to_make = folders_to_make,
            drive_id = drive_id
        )

    return {
        "name": folder_name,
        "id": folder_id,
        "parent": parent,
        "type": FOLDER_MIME_TYPE
    }

def upload_drive_file(google_drive_client, source_file_info: dict, destination_file_name: str, parent_id: str, drive_id = False):
    metadata = {
        "name": destination_file_name,
        "mimeType": source_file_info["guessed_mime_type"],
        "parents": [parent_id]
    }

    media = MediaFileUpload(
        filename = source_file_info["path"],
        # Exclude mimetype for simple uploads because apparently they can infer it
        # mimetype = source_file_info["guessed_mime_type"]
    )

    upload_args = {
        "body": metadata,
        "media_body": media,
        "fields": "id"
    }

    if drive_id:
        upload_args["supportsAllDrives"] = True

    logger.debug("(upload_drive_file) Invoking Drive API")
    logger.debug("    body (metadata): %s", metadata)
    logger.debug("    media_body: %s\n", media)

    try:
        result = google_drive_client.files().create(**upload_args).execute()
    except HttpError as error:
        logger.fatal("An error occurred while uploading the file:")
        logger.fatal("    %s\n", error)

    logger.debug("(upload_drive_file) Response:")
    logger.debug("    %s", result)

    return result.get("id")

### Specific purpose methods

def get_source_file_info(source_file_path: str) -> dict:
    # Clean up the path, and translate `~` to a full path
    source_file_path_normalized = os.path.expanduser(os.path.normpath(source_file_path))

    if not os.path.exists(source_file_path_normalized):
        raise FileNotFoundError(f"The file specified at '{source_file_path_normalized}' does not exist!")

    if not os.path.isfile(source_file_path_normalized):
        raise NotImplementedError(f"'{source_file_path_normalized}' appears to be a directory! This tool only supports individual files.")

    # Check the file's mime type. The `or` statement provides Drive's default when a type isn't
    # specified, so we use this as a fallback when Python can't figure out what a file is.
    guessed_mime_type, _ = mimetypes.guess_type(source_file_path_normalized, strict = False) or "application/octet-stream", None

    # Get the file's size in bytes
    file_size = os.path.getsize(source_file_path_normalized)

    return {
        "path": source_file_path_normalized,
        "guessed_mime_type": guessed_mime_type,
        "size": file_size
    }

# TODO: maybe change this big tuple into a class
def get_destination_info(google_drive_client, source_file_path: str, destination_path: str, drive_id: str = False) -> tuple:
    """Checks the destination Drive for existing directories to use, and whether there are any files with the same name as the file to be uploaded.
    If there are, prepares a new name for the file.

    Returns:
        tuple(List[dict], List[str], str): A list of folders present in dictionary form {name: `str`, id: `str`, parent: `str`, type: `str`}, a list of folders missing, and the name to be used when uploading the target file.
    """

    local_root_folder_info = None
    if drive_id:
        local_root_folder_info = [{"name": "root", "id": drive_id, "parent": "root", "type": FOLDER_MIME_TYPE}]
    else:
        local_root_folder_info = [ROOT_FOLDER_INFO]

    # If the destination is the default `/`, we're just uploading to the root of the Drive,
    # so we return quickly.
    if destination_path == '/':
        return local_root_folder_info, [], os.path.basename(source_file_path)

    # Clean up and split the destination into usable parts.
    parent_folders, destination_file_name = os.path.split(destination_path)

    # The last operation returns the parent folders as a single string, so we split that result too
    # Also run the path through normpath() first to remove any oddities in the path
    parent_folders = os.path.normpath(parent_folders).split(os.sep)

    # If the split result doesn't have a file for us, use the source file's namek
    if not destination_file_name:
        destination_file_name = os.path.basename(source_file_path)

    # If the top-most parent folder is "", it means it was "/", the root directory,
    # so we remove it, as we always assume the first folder is relative to the root.
    # Alternatively, if it is '.', then the input was a single string, and os.path.normpath
    # added the dot, which we also remove.
    if not parent_folders[0] or parent_folders[0] == '.':
        del parent_folders[0]

    folders_present = []
    folders_missing = []

    # I just know there's a way to do this with recursion, but I can't wrap my head around it right now
    for index, this_folder in enumerate(parent_folders):
        parent = None
        if index == 0:
            parent = local_root_folder_info[0]["id"]
        else:
            # This should be safe as, if we get here, we found at least one folder
            parent = folders_present[index - 1]["id"]

        found_folders = list_drive_files(
            google_drive_client = google_drive_client,
            query = [
                f"mimeType = '{FOLDER_MIME_TYPE}'",
                f"'{parent}' in parents",
                f"name = '{escape_google_api_query_string(this_folder)}'",
                "trashed = false"
                ],
            fields = ["files(id, name, parents)"],
            drive_id = drive_id
        )

        if found_folders:
            logger.debug("(get_destination_info) Found %i folders with name %s\n", len(found_folders), this_folder)
            folders_present.append({"name": this_folder, "id": found_folders[0]["id"], "parent": parent, "type": FOLDER_MIME_TYPE})
        else:
            # We didn't find anything, so all that remains are folders that must be created
            folders_missing.extend(parent_folders[index:len(parent_folders)])
            break
    logger.debug("(get_destination_info) We found %i folders:", len(folders_present))
    logger.debug("    %s", folders_present)
    logger.debug("    %i folders are missing:", len(folders_missing))
    logger.debug("    %s\n", folders_missing)

    # If any folders are missing, we don't need to do any further actions
    if folders_missing:
        return folders_present, folders_missing, destination_file_name

    # If we're working with the root directory, the above loop will have never run,
    # so manually populate found_folders with the root.
    if not folders_present:
        folders_present = local_root_folder_info

    # If all folders are present, check if the destination file is present too.
    # We search for the file without the extension to also include possible existing duplicates in the same directory.
    file_name_base, file_extension = os.path.splitext(destination_file_name)

    found_files = list_drive_files(
            google_drive_client = google_drive_client,
            query = [
                f"'{folders_present[-1]["id"]}' in parents",
                f"name contains '{file_name_base.replace("'", "\\'")}'",
                "trashed = false"
                ],
            fields = ["files(id, name, parents)"],
            drive_id = drive_id
        )

    if not found_files:
        return folders_present, folders_missing, destination_file_name

    logger.info("Found a file in the destination directory with the same name as the file to be uploaded. Preparing new name.")
    destination_file_name = f"{file_name_base} ({len(found_files) + 1}){file_extension}"

    return folders_present, folders_missing, destination_file_name

### Entrypoint
def main():
    # Set up arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--source-file", required = True, help = "The file you wish to upload.")
    parser.add_argument("-d", "--destination-path", required = False, default = "/", help = "The destination for the file. If the path does not end in a file name, the source file's name will be used.")
    parser.add_argument("-n", "--drive-name", required = False, default = "My Drive", help = "The Google Drive to upload to. Defaults to the current user's Drive. Put quotation marks around the name if it has any spaces or special characters!")
    parser.add_argument("-v", "--verbose", required = False, help = "Enable verbose logging", action = "store_true")
    myargs = parser.parse_args()

    # Prepare logging
    log_level = logging.DEBUG if myargs.verbose else logging.INFO
    logging.basicConfig(level = log_level)

    # Before we do anything too strenuous, let's learn about the source file
    source_file_info = get_source_file_info(myargs.source_file)

    # Handle auth
    user_credentials = get_google_credentials()

    # Create Drive client
    client = build(serviceName = "drive", version = "v3", credentials = user_credentials)

    drive_id = False

    if not myargs.drive_name == "My Drive":
        drive_id = get_drive_id(client, myargs.drive_name)

    # Get info about the destination
    folders_present, folders_missing, destination_file_name = get_destination_info(client, myargs.source_file, myargs.destination_path, drive_id)

    parent_folder = None

    # Create any missing folders
    if folders_missing:
        parent_folder = create_missing_drive_folders(google_drive_client = client, parent = folders_present[-1]["id"], folders_to_make = folders_missing, drive_id = drive_id)
    else:
        parent_folder = folders_present[-1]

    # Finally, carry out the upload!
    result = upload_drive_file(
        google_drive_client = client,
        source_file_info = source_file_info,
        destination_file_name = destination_file_name,
        parent_id = parent_folder["id"],
        drive_id = drive_id
    )

    logger.info("File '%s' created! Google Drive ID %s\n", destination_file_name, result)

if __name__ == "__main__":
    main()
