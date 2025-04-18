from server.node_manager import MasterNode
from server.global_topic import GlobalTopicRegistry
from server.mom_instance import MOMInstance
from fastapi import FastAPI, HTTPException, Depends, Form, Request
from pydantic import BaseModel
import jwt
import json
import grpc
from server.auth import (
    hash_password,
    create_access_token,
    authenticate_user,
    fake_users_db,
    SECRET_KEY,
    ALGORITHM,
)
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

app = FastAPI()
master_node = MasterNode()  # Initialize MasterNode without hardcoded instances
mom_instance = MOMInstance(
    instance_name="rest_api_instance",
    master_node_url="http://localhost:8000",  # URL del nodo maestro
    grpc_port=50051  # Puerto gRPC de esta instancia
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

class MessageRequest(BaseModel):
    topic_name: str
    message: str

@app.post("/signup")
def signup(username: str = Form(...), password: str = Form(...)):
    """Signup a new user."""
    if username in fake_users_db:
        raise HTTPException(status_code=400, detail="Username already exists")
    fake_users_db[username] = {"hashed_password": hash_password(password)}
    return {"status": "Success", "message": f"User {username} created"}

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login a user and return a JWT token."""
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    access_token = create_access_token(data={"sub": form_data.username})
    return {"access_token": access_token, "token_type": "bearer"}

def get_current_user(token: str = Depends(oauth2_scheme)):
    """Get the current authenticated user."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None or username not in fake_users_db:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")


@app.post("/node/register")
def register_node(node_name: str = Form(...), hostname: str = Form(...), port: int = Form(...)):
    """Register a MOM node in the cluster from a remote machine."""
    master_node.add_instance(node_name=node_name, hostname=hostname, port=port)
    return {"status": "Success", "message": f"Node {node_name} registered successfully."}

@app.post("/node/remove")
def remove_instance(node_name: str, current_user: str = Depends(get_current_user)):
    """Remove a MOM node from the cluster by its name (authenticated)."""
    master_node.remove_instance(node_name)
    return {"status": "Success", "message": f"Node {node_name} removed from the cluster."}

@app.post("/topic/{topic_name}")
def create_topic(topic_name: str, num_partitions: int = 3, current_user: str = Depends(get_current_user)):
    """Create a new topic (authenticated)."""
    try:
        master_node.create_topic(topic_name, num_partitions)
        return {"status": "Success", "message": f"Topic {topic_name} created with {num_partitions} partitions by {current_user}"}
    except Exception as e:
        print(f"Error creating topic: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating topic: {str(e)}")

@app.post("/list/topics")
def list_topics():
    registry = GlobalTopicRegistry()
    topics = registry.list_topics()
    return {"status": "Success", "topics": topics}

@app.post("/list/instances")
def list_instances():
    """List all MOM nodes in the cluster."""
    instances = master_node.list_instances()
    return {"status": "Success", "instances": instances}


@app.post("/message")
def send_message(request: MessageRequest, current_user: str = Depends(get_current_user)):
    """Send a message to a topic (authenticated)."""
    response = mom_instance.send_message_to_topic(request.topic_name, request.message)
    return {"status": "Success", "message": f"Message sent to topic {request.topic_name} via {response.status}"}

@app.post("/topic/{topic_name}/info")
def get_topic_info(topic_name: str, current_user: str = Depends(get_current_user)):
    """Get information about a topic and its partitions."""
    registry = GlobalTopicRegistry()
    partition_count = registry.get_partition_count(topic_name)
    partition_stats = registry.get_partition_stats(topic_name)
    
    return {
        "status": "Success",
        "topic_name": topic_name,
        "partition_count": partition_count,
        "partition_stats": partition_stats
    }

@app.post("/message/{topic_name}/{partition_id}")
def get_message_from_partition(
    topic_name: str, 
    partition_id: int, 
    current_user: str = Depends(get_current_user)
):
    """Get a message from a specific partition."""
    registry = GlobalTopicRegistry()
    message = registry.get_message_from_partition(topic_name, partition_id)
    
    if message:
        return {
            "status": "Success",
            "topic_name": topic_name,
            "partition_id": partition_id,
            "message": message
        }
    else:
        return {
            "status": "Empty",
            "topic_name": topic_name,
            "partition_id": partition_id,
            "message": "No messages available in this partition"
        }
