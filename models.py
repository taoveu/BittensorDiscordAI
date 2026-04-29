from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text, JSON, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime

from database import Base

class Subnet(Base):
    __tablename__ = "subnets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    discord_url = Column(String, default="https://discord.com/channels/@me")
    is_scraping_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    analyses = relationship("Analysis", back_populates="subnet", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="subnet", cascade="all, delete-orphan")

class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    subnet_id = Column(Integer, ForeignKey("subnets.id"))
    sentiment_score = Column(Float) # -1 to 1
    executive_synthesis = Column(Text) # Expanded for deeper synthesis
    critical_points = Column(JSON) # List of 3 strings
    raw_json_file = Column(String) # For reference
    author_count = Column(Integer, default=0) # Tracks number of unique contributors
    message_count = Column(Integer, default=0) # Tracks raw message volume for Momentum calculation
    created_at = Column(DateTime, default=datetime.utcnow)

    subnet = relationship("Subnet", back_populates="analyses")

class GlobalConfig(Base):
    __tablename__ = "global_config"

    key = Column(String, primary_key=True, index=True)
    value = Column(String) # Store string representation, cast logically (e.g. "True"/"False")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(String, primary_key=True, index=True) # Discord Snowflake ID (e.g. "123456789012345678")
    subnet_id = Column(Integer, ForeignKey("subnets.id"))
    author = Column(String)
    content = Column(Text)
    timestamp = Column(DateTime)
    
    subnet = relationship("Subnet", back_populates="messages")
