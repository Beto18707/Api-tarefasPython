from typing import Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, ValidationError, field_validator
from enum import Enum

from fastapi import FastAPI, HTTPException, status, Query, Path, Body, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import bcrypt

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.sql import func

DATABASE_URL = "mysql+pymysql://root:12345@localhost:3306/pythonTarefas"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class TaskStatusEnum(str, Enum):
    pending = "pending"
    completed = "completed"

class DBUser(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    tasks = relationship("DBTask", back_populates="owner")

class DBTask(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    status = Column(SQLEnum(TaskStatusEnum), default=TaskStatusEnum.pending, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    owner = relationship("DBUser", back_populates="tasks")

def create_db_tables():
    Base.metadata.create_all(bind=engine)

SECRET_KEY = "TESTE" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

class UserCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    email: str = Field(..., max_length=255, pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    password: str = Field(..., min_length=6, max_length=255)

class LoginRequest(BaseModel):
    email: str
    password: str

class User(BaseModel):
    id: int
    name: str
    email: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    status: TaskStatusEnum = Field(TaskStatusEnum.pending)

class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    status: Optional[TaskStatusEnum] = Field(None)


class Task(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    status: TaskStatusEnum
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

app = FastAPI(
    title="API de Tarefas Simples (Python/FastAPI)",
    description="Uma API de tarefas recriada em Python com FastAPI para aprendizado.",
    version="1.0.0",
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[int] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        user = db.query(DBUser).filter(DBUser.id == user_id).first()
        if user is None:
            raise credentials_exception
        return User.model_validate(user)
    except JWTError:
        raise credentials_exception
    except Exception:
        raise credentials_exception

@app.on_event("startup")
def on_startup():
    create_db_tables()
    print("Tabelas do banco de dados criadas ou já existentes.")

@app.get("/")
async def read_root():
    return {"message": "API de Gerenciamento de Tarefas está funcionando!"}

@app.post("/auth/register", response_model=User, status_code=status.HTTP_201_CREATED)
async def register(user_create: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter(DBUser.email == user_create.email).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="E-mail já registrado."
        )
    
    hashed_password = bcrypt.hashpw(user_create.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    db_user = DBUser(
        name=user_create.name,
        email=user_create.email,
        hashed_password=hashed_password,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return User.model_validate(db_user)

@app.post("/auth/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter(DBUser.email == form_data.username).first()
    
    if not db_user or not bcrypt.checkpw(form_data.password.encode('utf-8'), db_user.hashed_password.encode('utf-8')):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(db_user.id)}, 
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/tasks/", response_model=Task, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_create: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_task = DBTask(
        title=task_create.title,
        description=task_create.description,
        status=task_create.status,
        user_id=current_user.id,
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    
    return Task.model_validate(db_task)

@app.get("/tasks/", response_model=List[Task])
async def get_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status_filter: Optional[TaskStatusEnum] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    sort_by: Optional[str] = Query("created_at", enum=["created_at", "updated_at", "title", "status"]),
    sort_order: Optional[str] = Query("desc", enum=["asc", "desc"])
):
    query = db.query(DBTask).filter(DBTask.user_id == current_user.id)
    
    if status_filter:
        query = query.filter(DBTask.status == status_filter)
    
    if search:
        search_lower = f"%{search.lower()}%"
        query = query.filter(
            (DBTask.title.ilike(search_lower)) | 
            (DBTask.description.ilike(search_lower))
        )
    
    if sort_by:
        sort_column = getattr(DBTask, sort_by)
        if sort_order.lower() == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())
            
    offset = (page - 1) * limit
    db_tasks = query.offset(offset).limit(limit).all()

    return [Task.model_validate(task) for task in db_tasks]

@app.get("/tasks/{task_id}", response_model=Task)
async def get_task_by_id(
    task_id: int = Path(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_task = db.query(DBTask).filter(DBTask.id == task_id, DBTask.user_id == current_user.id).first()
    if not db_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tarefa não encontrada."
        )
    return Task.model_validate(db_task)

@app.put("/tasks/{task_id}", response_model=Task)
async def update_task(
    task_id: int = Path(...),
    task_update: TaskUpdate = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_task = db.query(DBTask).filter(DBTask.id == task_id, DBTask.user_id == current_user.id).first()
    if not db_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tarefa não encontrada."
        )
    
    updates = task_update.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(db_task, key, value)
    
    db.commit()
    db.refresh(db_task)
    
    return Task.model_validate(db_task)

@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int = Path(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_task = db.query(DBTask).filter(DBTask.id == task_id, DBTask.user_id == current_user.id).first()
    if not db_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tarefa não encontrada."
        )
    
    db.delete(db_task)
    db.commit()
    
    return