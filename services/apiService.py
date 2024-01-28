from http import client
import sys
import os
sys.path.append(os.path.realpath('../lib'))
import yaml
from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import JSONResponse
import sqlite3
import aiosqlite
import asyncio
from pydantic import BaseModel

with open("../config.yaml", 'r') as stream:
    config = (yaml.safe_load(stream))

userPortalUrl = config.get('captiveApi', {}).get('portal', {}).get('url', 'https://example.org/portal.html')
userPortalEnabled = config.get('captiveApi', {}).get('portal', {}).get('enabled', False)
venueInfoUrl = config.get('captiveApi', {}).get('venueInfo', {}).get('url', "https://exampleVenue.org/info.html")
venueInfoEnabled = config.get('captiveApi', {}).get('venueInfo', {}).get('enabled', False)
allowUnknownClients = config.get('captiveApi', {}).get('allowUnknownClients', False)
sqlite3Path = config.get('sqlite3', {}).get('path', False)

api = FastAPI(version='1.0', title=f'Captive Portal API', description='Captive Portal API - based on RFC8908.')

errorResponses = {
    404: {"description": "Not found"},
    500: {"description": "Server error"}
}

captiveResponseHeader = {"Content-Type": "application/captive+json"}
jsonResponseHeader = {"Content-Type": "application/json"}

class ReleaseModel(BaseModel):
    client_identifier: str

class HoldCaptiveModel(BaseModel):
    client_identifier: str

captivePortalRouter = APIRouter(
    prefix="/captive-portal",
    tags=["api"],
    responses=errorResponses,
)

operationRouter = APIRouter(
    prefix="/operation",
    tags=["client"],
    responses=errorResponses,
)

def setup_database():
    """
    Builds the SQLite3 Database.
    """
    connection = sqlite3.connect(sqlite3Path)
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS clients (identifier TEXT, captive BOOLEAN, user_portal_url TEXT, venue_info_url TEXT, can_extend_session BOOLEAN, seconds_remaining BIGINT, bytes_remaining BIGINT)")

setup_database()


async def release_client_from_captivity(client_identifier: str) -> bool:
    """
    Sets a clients captive state to False.
    """

    async with aiosqlite.connect(sqlite3Path) as db:
        await db.execute(f"UPDATE clients SET captive = false WHERE identifier = ?", client_identifier)
        await db.commit()

async def hold_client_captive(client_identifier: str) -> bool:
    """
    Sets a clients captive state to True.
    """

    async with aiosqlite.connect(sqlite3Path) as db:
        await db.execute(f"UPDATE clients SET captive = true WHERE identifier = ?", client_identifier)
        await db.commit()

async def add_client_to_database(client_identifier: str) -> bool:
    """
    Adds a provided client to the database.
    """

    async with aiosqlite.connect(sqlite3Path) as db:
        await db.execute(f"INSERT INTO clients VALUES ({client_identifier}, true, {userPortalUrl if userPortalEnabled else 'null'}, {venueInfoUrl if venueInfoEnabled else 'null'}, null, null, null)")
        await db.commit()
    
    return True

async def search_database_for_client(client_identifier: str) -> dict:
    """
    Searches the database for the given client_identifier.
    Returns a dictionary on success, or None on failure.
    """
    client = {}

    async with aiosqlite.connect(sqlite3Path) as db:
        searchResult = (await db.execute(f"SELECT * FROM clients WHERE identifier = ?", client_identifier).fetchone())
        if searchResult:
            if searchResult[1]:
                client['captive'] = searchResult[1]
            if searchResult[2]:
                client['user-portal-url'] = searchResult[2]
            if searchResult[3]:
                client['venue-info-url'] = searchResult[3]
            if searchResult[4]:
                client['can-extend-session'] = searchResult[4]
            if searchResult[5]:
                client['seconds-remaining'] = searchResult[5]
            if searchResult[6]:
                client['bytes-remaining'] = searchResult[6]
        return None

async def get_client(client_identifier: str) -> dict:
    """
    Checks the database for the presence of a client, and returns the captivity status if found.
    Will always returns captive: false if allowUnknownClient is enabled in config.
    """
    client = {"captive": True}

    searchResult = await search_database_for_client(client_identifier=client_identifier)
    if not searchResult:
        await add_client_to_database(client_identifier=client_identifier)
    
    if allowUnknownClients:
        client['captive'] = False
    
    if userPortalEnabled:
        client['user-portal-url'] = userPortalUrl
    
    if venueInfoUrl:
        client['venue-info-url'] = venueInfoUrl

    return client

@captivePortalRouter.get("/captive-portal/api/{client_identifier}")
async def get_client_status(client_identifier):
    clientStatus = await get_client(client_identifier=client_identifier)
    return JSONResponse(content=clientStatus, headers=captiveResponseHeader)

@operationRouter.post("/release/")
async def release_client(releaseClient: ReleaseModel):
    client_identifier = releaseClient.get('client_identifier', None)
    if not client_identifier:
        raise HTTPException(status_code=400, detail="client_identifier missing")
    result = await release_client_from_captivity(client_identifier=client_identifier)

    return JSONResponse(content={200: {"result": result}}, headers=jsonResponseHeader)

@operationRouter.post("/holdCaptive/")
async def hold_client_captive(releaseClient: ReleaseModel):
    client_identifier = releaseClient.get('client_identifier', None)
    if not client_identifier:
        raise HTTPException(status_code=400, detail="client_identifier missing")
    result = await hold_client_captive(client_identifier=client_identifier)

    return JSONResponse(content={200: {"result": result}}, headers=jsonResponseHeader)

api.include_router(captivePortalRouter)
api.include_router(operationRouter)