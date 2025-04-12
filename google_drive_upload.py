#! /usr/bin/env python3
import os
import sys
import mimetypes
import argparse
import logging
import json
import socket

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

AUTH_CLIENT_CREDENTIALS_DEFAULT_LOCATION_NO_EXPAND = "~/.owi/google_drive_uploader/credentials.json"
AUTH_CLIENT_CREDENTIALS_DEFAULT_LOCATION = os.path.expanduser(AUTH_CLIENT_CREDENTIALS_DEFAULT_LOCATION_NO_EXPAND)
AUTH_CLIENT_CREDENTIALS_PATH_ENV_VAR_NAME = "OWI_GOOGLE_DRIVE_UPLOADER_CREDENTIALS_PATH"
AUTH_CLIENT_CREDENTIALS_TEXT_ENV_VAR_NAME = "OWI_GOOGLE_DRIVE_UPLOADER_CREDENTIALS_TEXT"

AUTH_CLIENT_TOKEN_DEFAULT_LOCATION_NO_EXPAND = "~/.owi/google_drive_uploader/token.json"
AUTH_CLIENT_TOKEN_DEFAULT_LOCATION = os.path.expanduser(AUTH_CLIENT_TOKEN_DEFAULT_LOCATION_NO_EXPAND)
AUTH_CLIENT_TOKEN_PATH_ENV_VAR_NAME = "OWI_GOOGLE_DRIVE_UPLOADER_TOKEN_PATH"

# Folders in Google Drive have a special MIME type
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

# Magic string which can be used in and ID field to refer to the root
DRIVE_ROOT_FOLDER_NAME = "root"
ROOT_FOLDER_INFO = {"name": "root", "id": "root", "parent": "root", "type": FOLDER_MIME_TYPE}

### Authentication methods

def invoke_google_authentication(api_credentials, token = None, unattended: bool = False) -> tuple:
    """Gets the user's Google credentials for use in the script.
    If there are no credentials, or if they're expired, runs the user
    through the authentication process.

    Lovingly adapted from Google's Python Google Drive quickstart: https://developers.google.com/workspace/drive/api/quickstart/python

    Returns:
        tuple(google.oauth2.credentials.Credentials, bool): The retrieved credentials, and whether to save the token.
    """
    creds = None
    save_token = False
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if token:
        creds = Credentials.from_authorized_user_info(token, SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if unattended:
                logger.fatal("Need user to authenticate with Google, but we don't seem to be in an interactive environment! Exiting...")
                sys.exit(2)

            port = 0
            open_browser = True
            prompt_message = InstalledAppFlow._DEFAULT_AUTH_PROMPT_MESSAGE

            if not in_desktop_environment():
                user_response = input("We need to authenticate with Google, but we don't seem to be running in a graphical environment. Would you like to use SSH port forwarding to use another machine for the authentication process? (y/n)")
                while user_response not in ["y", "Y", "n", "N"]:
                    user_response = input("Invalid input! Type 'y' or 'n'.")

                if user_response in ["n", "N"]:
                    logger.fatal("Cannot authenticate with Google. Exiting...")
                    sys.exit(1)

                # Allocate a socket, then immediately release it to get a (mostly) guaranteed unused one
                temp_socket = socket.socket()
                temp_socket.bind(('localhost', 0))
                port = temp_socket.getsockname()[1]
                temp_socket.close()

                print(f"Run the following command in a separate terminal to open an SSH tunnel: ssh -L localhost:{port}:localhost:{port} <user>@<address>")
                open_browser = False
                prompt_message = "Once you have established the tunnel, open this URL in your browser: {url}"

            flow = InstalledAppFlow.from_client_config(api_credentials, SCOPES)
            creds = flow.run_local_server(port = port, open_browser = open_browser, authorization_prompt_message = prompt_message)
        # Save the credentials for the next run
        save_token = True
    return creds, save_token

def set_google_token(token, token_location: str = AUTH_CLIENT_TOKEN_DEFAULT_LOCATION):
    try:
        if token_location == AUTH_CLIENT_TOKEN_DEFAULT_LOCATION and not os.path.exists(os.path.dirname(token_location)):
            logger.info("Default location for token '%s' doesn't exist. Creating...", token_location)
            os.makedirs(name = os.path.dirname(token_location), mode=0o700, exist_ok = True)

        with open(token_location, "w") as file:
            file.write(token.to_json())
            return
    # Catching BaseException is very broad, but I just want to catch this so I can give a nicer error message before exiting
    except BaseException as error:
        logger.fatal("Error while saving Google API token to location '%s': %s", token_location, error)
        sys.exit(1)

def get_google_token(token_location: str = AUTH_CLIENT_TOKEN_DEFAULT_LOCATION) -> tuple:
    # Priority list:
    # 1. CLI argument
    # 2. Environment variable path
    # 3. Default filesystem location

    # 1. CLI argument
    if not token_location == AUTH_CLIENT_TOKEN_DEFAULT_LOCATION:
        if not os.path.exists(token_location):
            logger.info("Google API token not found at path '%s'. Will generate new token.", token_location)
            return None, token_location
        try:
            with open(token_location, "r") as file:
                return json.load(file), token_location
        # Catching BaseException is very broad, but I just want to catch this so I can give a nicer error message before exiting
        except BaseException as error:
            logger.fatal("Error while loading Google API token from command-line argument at '%s': %s", token_location, error)
            sys.exit(1)

    # 2. Environment variable path
    env_var_path_value = os.environ.get(AUTH_CLIENT_TOKEN_PATH_ENV_VAR_NAME, "")

    if env_var_path_value:
        if not os.path.exists(env_var_path_value):
            logger.info("Google API token not found at path '%s' from in environment variable '%s'. Will generate new token.", env_var_path_value, AUTH_CLIENT_TOKEN_PATH_ENV_VAR_NAME)
            return None, env_var_path_value
        try:
            with open(env_var_path_value, "r") as file:
                return json.load(file), env_var_path_value
        except BaseException as error:
            logger.fatal("Encountered error while loading Google API token from file set in '%s': %s", AUTH_CLIENT_TOKEN_PATH_ENV_VAR_NAME, error)
            sys.exit(1)

    # 3. Default filesystem location
    if not os.path.exists(token_location):
        logger.info("Google API token not found at path '%s'. Will generate new token.", token_location)
        return None, token_location
    try:
        with open(token_location, "r") as file:
            return json.load(file), token_location
    except BaseException as error:
        logger.fatal("Encountered error while loading Google API token from file at '%s': %s", token_location, error)
        sys.exit(1)

def get_google_credentials(credentials_location: str = AUTH_CLIENT_CREDENTIALS_DEFAULT_LOCATION):
    # Priority list:
    # 1. CLI argument
    # 2. Environment variable text
    # 3. Environment variable path
    # 4. Default filesystem location

    # 1. CLI argument
    if not credentials_location == AUTH_CLIENT_CREDENTIALS_DEFAULT_LOCATION:
        if not os.path.exists(credentials_location):
            logger.fatal("Argument for path '%s' to Google API credentials JSON file was invalid!", credentials_location)
            sys.exit(1)
        try:
            with open(credentials_location, "r") as file:
                return json.load(file)
        # Catching BaseException is very broad, but I just want to catch this so I can give a nicer error message before exiting
        except BaseException as error:
            logger.fatal("Error while loading Google API credentials from command-line argument: %s", error)
            sys.exit(1)

    # 2. Environment variable text
    env_var_text_value = os.environ.get(AUTH_CLIENT_CREDENTIALS_TEXT_ENV_VAR_NAME, "")

    if env_var_text_value:
        try:
            return json.loads(env_var_text_value)
        except BaseException as error:
            logger.fatal("Error while loading JSON text for Google API credentials set in environment variable '%s': %s", AUTH_CLIENT_CREDENTIALS_TEXT_ENV_VAR_NAME, error)
            sys.exit(1)

    # 3. Environment variable path
    env_var_path_value = os.environ.get(AUTH_CLIENT_CREDENTIALS_PATH_ENV_VAR_NAME, "")

    if env_var_path_value:
        env_var_path_value = os.path.expanduser(env_var_path_value)
        if not os.path.exists(env_var_path_value):
            logger.fatal("File at path '%s' for Google API credentials set in environment variable '%s' doesn't exist!", env_var_path_value, AUTH_CLIENT_CREDENTIALS_PATH_ENV_VAR_NAME)
            sys.exit(1)
        try:
            with open(env_var_path_value, "r") as file:
                return json.load(file)
        except BaseException as error:
            logger.fatal("Encountered error while loading Google API credentials from file set in '%s': %s", AUTH_CLIENT_CREDENTIALS_PATH_ENV_VAR_NAME, error)
            sys.exit(1)

    # 4. Default filesystem location
    if not os.path.exists(credentials_location):
        logger.fatal("Could not locate Google API credential file at '%s', and no alternative methods of loading credentials were used! Did you generate a credentials.json file? Check the README!", credentials_location)
        sys.exit(1)

    try:
        with open(credentials_location, "r") as file:
            return json.load(file)
    except BaseException as error:
        logger.fatal("Encountered error while loading Google API credentials from file at '%s': %s", credentials_location, error)
        sys.exit(1)

def in_desktop_environment():
    if sys.platform in ["win32", "cygwin"]:
        return "windows"
    elif sys.platform == "darwin":
        return "mac"
    else:
        return os.environ.get("DESKTOP_SESSION")

### Google API utility methods

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

def get_drive_id(google_drive_client, drive_name: str, unattended: bool = False):
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
        if unattended:
            logger.fatal("Got more than one result while getting the id of the shared Drive '%s', but cannot prompt user as we're in unattended mode! Exiting...", drive_name)
            sys.exit(2)
        logger.warning("Got more than one result while getting the id of the shared Drive '%s'! Which one should be used?", drive_name)
        for index, drive in enumerate(response["drives"]):
            print(f"{index}: {drive['name']} (id: {drive['id']})")

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

    parent_folders = []
    destination_file_name = None

    # If the destination is the default `/`, we're just uploading to the root of the Drive,
    # so we skip some steps
    if destination_path != '/':
        # return local_root_folder_info, [], os.path.basename(source_file_path)
        # Clean up and split the destination into usable parts.
        parent_folders, destination_file_name = os.path.split(destination_path)

        # The last operation returns the parent folders as a single string, so we split that result too
        # Also run the path through normpath() first to remove any oddities in the path
        parent_folders = os.path.normpath(parent_folders).split(os.sep)

    # If the split result doesn't have a file for us, use the source file's name
    if not destination_file_name:
        destination_file_name = os.path.basename(source_file_path)

    # If the top-most parent folder is "", it means it was "/", the root directory,
    # so we remove it, as we always assume the first folder is relative to the root.
    # Alternatively, if it is '.', then the input was a single string, and os.path.normpath
    # added the dot, which we also remove.
    if parent_folders and (not parent_folders[0] or parent_folders[0] == '.'):
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
                f"'{folders_present[-1]['id']}' in parents",
                f"name contains '{escape_google_api_query_string(file_name_base)}'",
                "trashed = false"
                ],
            fields = ["files(id, name, parents)"],
            drive_id = drive_id
        )

    if not found_files:
        return folders_present, folders_missing, destination_file_name

    logger.info("Found a file in the destination directory with the same name as the file to be uploaded. Preparing new name.")
    number = 1
    if len(found_files) > 1:
        numbers_list = []
        for this_file in found_files:
            # Okay this is wildly cursed but it makes sense. Here's what's going on:
            # We have possibly many files in the pattern of <base name> (<number>).<extension>
            # and we already have all those bits separately, and know how long they are.
            # This line takes every file returned that match that pattern, removes the extension,
            # removes the base name + 2 characters (the ` (` before the number),
            # and removes the last `)` character, leaving just the number.
            value = os.path.splitext(this_file["name"])[0][(len(file_name_base) + 2):-1]

            if value.isdigit():
                numbers_list.append(int(value))
        number = max(numbers_list) + 1
    destination_file_name = f"{file_name_base} ({number}){file_extension}"

    return folders_present, folders_missing, destination_file_name

### Entrypoint
def main():
    # Set up arguments
    parser = argparse.ArgumentParser(
        formatter_class = argparse.RawDescriptionHelpFormatter,
        description = f"""
Uploads a specified file to Google Drive. If credentials aren't found, guides user through Google authentication.

Regarding interactive authentication:
On first run, this tool will guide the user through authenticating with Google. This process requires a desktop environment and a browser. If you wish to use this program on a device that doesn't have a browser, like a server, the script will help you set up a tunnel so you can complete the authentication flow from you workstation's browser.
Alternatively, you can pre-generate a token by running the program on a workstation with a desktop environment. Run the program with the --token-json-path argument set, then once the file has been created, copy it to the destination computer.

In addition to the default locations and arguments for setting custom locations for credential and token files, this application is also aware of these environment variables:
    * {AUTH_CLIENT_CREDENTIALS_PATH_ENV_VAR_NAME}: A path to a Google API OAuth credentials JSON.
    * {AUTH_CLIENT_CREDENTIALS_TEXT_ENV_VAR_NAME}: The raw text of a Google API OAuth credential JSON blob.
    * {AUTH_CLIENT_TOKEN_PATH_ENV_VAR_NAME}: A path to a JSON file containing a Google API OAuth token.

The order of precedence this program follows for these options is:
1. CLI argument
2. Environment variable text (credential JSON only)
3. Environment variable path
4. Default filesystem location

When this program gets new or refreshed token data, it will save that token to a path following the above precedent.
    """
    )
    parser.add_argument("-s", "--source-file", required = True, help = "The file you wish to upload.")
    parser.add_argument("-d", "--destination-path", required = False, default = "/", help = "The destination for the file. If the path does not end in a file name, the source file's name will be used.")
    parser.add_argument("-n", "--drive-name", required = False, default = "My Drive", help = "The Google Drive to upload to. Defaults to the current user's Drive. Put quotation marks around the name if it has any spaces or special characters!")
    parser.add_argument("-c", "--credentials-json-path", required = False, default = AUTH_CLIENT_CREDENTIALS_DEFAULT_LOCATION, help = f"Path to a Google API credentials file to use. Defaults to the path '{AUTH_CLIENT_CREDENTIALS_DEFAULT_LOCATION_NO_EXPAND}'.")
    parser.add_argument("-t", "--token-json-path", required = False, default = AUTH_CLIENT_TOKEN_DEFAULT_LOCATION, help = f"Path to a Google API token file, in JSON format, to use. If nothing is found at this path, or the token within is expired, a new or updated file will be written to this location. Defaults to the path '{AUTH_CLIENT_TOKEN_DEFAULT_LOCATION_NO_EXPAND}'")
    parser.add_argument("-u", "--unattended", required = False, action = "store_true", help = "Run in unattended mode. Prevents any prompts for user interaction, failing with a positive exit code (2). If the program can't detect an interactive environment, it will set this to true.")
    parser.add_argument("-v", "--verbose", required = False, action = "store_true", help = "Enable verbose logging")
    myargs = parser.parse_args()

    # Prepare logging
    log_level = logging.DEBUG if myargs.verbose else logging.INFO
    logging.basicConfig(level = log_level)

    unattended = myargs.unattended or not sys.stdout.isatty()
    if unattended:
        logger.info("Running in unattended mode")
        if myargs.unattended:
            logger.verbose("Reason: --unattended flag set by user")
        if not sys.stdout.isatty():
            logger.verbose("Reason: No TTY device was detected on stdOut. sys.stdout.isatty() returned False.")

    # Before we do anything too strenuous, let's learn about the source file
    source_file_info = get_source_file_info(myargs.source_file)

    # Handle auth:
    # Get the our credentials
    api_credentials = get_google_credentials(myargs.credentials_json_path)

    # Get the existing token, or None if it doesn't exist
    existing_token, true_location = get_google_token(myargs.token_json_path)

    # Run the authentication flow, return the validated token, and whether it needs to be saved
    token, save_token = invoke_google_authentication(api_credentials, existing_token, unattended)

    if save_token:
        set_google_token(token, true_location)

    # Create Drive client
    client = build(serviceName = "drive", version = "v3", credentials = token)

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
