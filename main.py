import asyncio, json, logging
from websockets.exceptions import ConnectionClosed
from starlette.websockets import WebSocket
from charge_point_handler import ChargePointHandler
from typing import List
from fastapi import Depends, FastAPI, HTTPException
from utils import WebSocketInterface
import uvicorn
import db_crud, models, schemas, database
from sqlalchemy.orm import Session
from database import engine
from contextlib import asynccontextmanager

logging.basicConfig(filename='ocpp.log',level=logging.DEBUG)
logger = logging.getLogger('ocpp')

@asynccontextmanager
async def lifespan(app: FastAPI):
    models.Base.metadata.create_all(bind=engine)
    yield


async def on_connect(websocket, charge_point_id):
    """
    For every new charge point that connects, create a ChargePoint instance
    and start listening for messages.
    """
    cp = ChargePointHandler(charge_point_id, websocket)
    try:
        await cp.start()
    except ConnectionClosed as err:
        logger.info(f'Connection from charging point with ID {cp.id} was closed. Info: {err.rcvd}')


app = FastAPI(
    title='Charging Point Operator API',
    version="0.0.1",
    lifespan=lifespan
)


@app.post("/charging_points", response_model=schemas.ChargingSubStation, tags=["Charging Points"])
def register_charging_substation(charging_substation_register: schemas.ChargingSubStationRegister,
                                 db: Session = Depends(database.get_db)):
    try:
        charging_substation = db_crud.register_charging_substation(db, charging_substation_register)
    except db_crud.DuplicateError as e:
        raise HTTPException(status_code=403, detail=f"{e}")
    return charging_substation


@app.get("/charging_points", response_model=List[schemas.ChargingSubStation], tags=["Charging Points"])
def get_charging_substations(db: Session = Depends(database.get_db)):
    return db_crud.get_charging_substations(db)


@app.post("/id_token", response_model=schemas.IdToken, tags=["ID token"])
def create_id_token(id_token_assign: schemas.IdTokenAssign,
                                 db: Session = Depends(database.get_db)):
    try:
        id_token = db_crud.create_id_token(db, id_token_assign)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"{e}")
    return id_token


@app.get("/id_token", response_model=schemas.IdToken,  tags=["ID token"])
def get_id_token(charging_substation_id, db: Session = Depends(database.get_db)):
    try:
        id_token = db_crud.get_id_token(db, charging_substation_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"{e}")
    return id_token


@app.put("/id_token/refresh", response_model=schemas.IdToken,  tags=["ID token"])
def refresh_id_token(charging_substation_id:str, db: Session = Depends(database.get_db)):
    try:
        id_token = db_crud.refresh_id_token(db, charging_substation_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"{e}")
    return id_token


@app.websocket('/ocpp1.6/{charge_point_id}')
async def websocket_listener(websocket_obj: WebSocket, charge_point_id: str, db: Session = Depends(database.get_db)):
    if db_crud.get_charging_substation(db, charge_point_id):
        await websocket_obj.accept()
        standard_ws = WebSocketInterface(websocket_obj)
        await on_connect(standard_ws, charge_point_id)
    else:
        logger.error(f"No charging point registration found for ID {charge_point_id}")
        await websocket_obj.close()

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=9999)