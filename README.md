# owi-python-test
Technical assessment for OWI - Python

## Setup

This is a self-contained script. Simply clone this repo to your desired location, and ensure the script is executable by running `chmod +x google_drive_upload`.

Install steps for a fresh Ubuntu Server 24.04 machine:
* `sudo apt update`
* `sudo apt install git pip python3-venv`
* Clone this repo - `git clone https://github.com/WillemToorenburgh/owi-python-test.git`
* `cd owi-python-test`
* [Create your Google API OAuth `credential.json` file](#generating-oauth-credentials)
* `python3 -m venv ./.venv`
* `source ./.venv/bin/activate`
* `pip install -r requirements.txt`
* `chmod +x ./google_drive_upload.py`
* Run the script: `./google_drive_upload.py --help`

## Authentication

On first run, this tool will guide the user through authenticating with Google. This process requires a desktop environment and a browser. If you wish to use this program on a device that doesn't have a browser, like a server, the script will help you set up a tunnel so you can complete the authentication flow from you workstation's browser.

### Generating OAuth credentials

You must provide your own Credentials file. Follow the instructions at [Google's Drive API Python Quickstart](https://developers.google.com/workspace/drive/api/quickstart/python#set-up-environment)'s `Set up your environment` section to generate a new `credentials.json` file. Once you have that file, 

### Non-interactive Authentication

Due to Google deprecating the out-of-band authentication method, this program cannot get an initial authorization token without a browser and interaction from the user.

You can, however, pre-generate a token by running the program on a workstation with a desktop environment. Run the program with the `--token-json-path` argument set, then once the file has been created, copy it to the destination computer.

### Justification for this authentication method

"Authentication for Mobile and Desktop Apps" was really the only option left to me. All the other methods were eliminated:

* Out-of-band authentication: deprecated and disabled a few years ago.
* OAuth for Limited Input Devices: this was my first choice, but I had to eliminate it as it only supports a [limited subset of Drive API scopes](https://developers.google.com/identity/protocols/oauth2/limited-input-device#allowedscopes), and the requirement for this script to work with Shared Drives necessitates the use of the [`https://www.googleapis.com/auth/drive.readonly` scope](https://developers.google.com/workspace/drive/api/reference/rest/v3/drives/list#authorization-scopes), which is not included in that subset.
* Service account: I was unable to find a role I could assign to the account that would allow it to work with Google Drive files. This may have been because I wasn't able to make the Google Cloud project associated with a Google Workspace.

### Additional ways to use credentials

In addition to the default locations and arguments for setting custom locations for credential and token files, this application is also aware of these environment variables:

* `OWI_GOOGLE_DRIVE_UPLOADER_CREDENTIALS_PATH`: A path to a Google API OAuth credentials JSON.
* `OWI_GOOGLE_DRIVE_UPLOADER_CREDENTIALS_TEXT`: The raw text of a Google API OAuth credential JSON blob.
* `OWI_GOOGLE_DRIVE_UPLOADER_TOKEN_PATH`: A path to a JSON file containing a Google API OAuth token.

The order of precedence this program follows for these options is:

1. CLI argument
1. Environment variable text (credential JSON only)
1. Environment variable path
1. Default filesystem location

When this program gets new or refreshed token data, it will save that token to a path following the above precedent.

## Note about Shared Drives

I was unable to test the Shared Drives functionality, as I don't have access to a Google Workspace. I've written in support for that **theoretically** works 🤞.

## Future work

* Package the script as a binary.
    > I actually got this working locally, but only as a dynamic binary, so it wouldn't launch on any machine that wasn't mine. I could probably figure this out given more time.
* Add support for uploading multiple files.
* Make sure Shared Drives support actually works!
* Add support for multi-part uploads.
