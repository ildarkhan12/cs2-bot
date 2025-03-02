import os
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import sessionmaker, declarative_base

# Настройка подключения к базе данных
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///cs2_bot.db').replace("postgres://", "postgresql://")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()

class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    total_rating = Column(Float, default=0.0)
    votes = Column(Integer, default=0)
    mvp_count = Column(Integer, default=0)
    first_place = Column(Integer, default=0)
    second_place = Column(Integer, default=0)
    third_place = Column(Integer, default=0)

class WeeklyPlayer(Base):
    __tablename__ = 'weekly_players'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)

class History(Base):
    __tablename__ = 'history'
    id = Column(Integer, primary_key=True)
    week = Column(Integer)
    mvp = Column(String)
    first_place = Column(String)
    second_place = Column(String)
    third_place = Column(String)

# Создаем таблицы в базе данных
Base.metadata.create_all(engine)

def get_session():
    return Session()