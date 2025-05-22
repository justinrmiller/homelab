#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit app for interacting with Valkey, Kafka, Qdrant, and PostgreSQL and MongoDB services.
"""

import os
import json
import random
import pandas as pd
import streamlit as st

import plotly.express as px
from typing import Tuple
from datetime import datetime

# Redis/Valkey
import valkey

# Kafka
from confluent_kafka import Producer, Consumer, KafkaError
from confluent_kafka.admin import AdminClient, NewTopic
from typing import Tuple
import requests

# Qdrant
from qdrant_client import QdrantClient
from qdrant_client.http import models

# PostgreSQL
import psycopg2
from sqlalchemy import create_engine, text
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# MongoDB
from pymongo import MongoClient
from pymongo.errors import PyMongoError

# Load environment variables (useful for local development)
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Set page configuration
st.set_page_config(
    page_title="Services Dashboard",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Service connection parameters from environment variables
VALKEY_HOST = os.environ.get("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.environ.get("VALKEY_PORT", 6379))
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", 6333))
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "172.17.0.1")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", 5432))
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "postgres")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "postgres")
POSTGRES_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
MONGODB_HOST = os.environ.get("MONGODB_HOST", "localhost")
MONGODB_PORT = int(os.environ.get("MONGODB_PORT", 27017))
MONGODB_USER = os.environ.get("MONGODB_USER", "mongo")
MONGODB_PASSWORD = os.environ.get("MONGODB_PASSWORD", "mongo")
MONGODB_DB = os.environ.get("MONGODB_DB", "homelab")

# Open WebUI
OPENWEBUI_HOST = os.environ.get("OPENWEBUI_HOST", "localhost")
OPENWEBUI_PORT = int(os.environ.get("OPENWEBUI_PORT", 8082))
OPENWEBUI_HEALTH_URL = f"http://{OPENWEBUI_HOST}:{OPENWEBUI_PORT}/healthz"

# Hasura
HASURA_HOST = os.environ.get("HASURA_HOST", "host.docker.internal")
HASURA_PORT = int(os.environ.get("HASURA_PORT", 8080))
HASURA_GRAPHQL_URL = f"http://{HASURA_HOST}:{HASURA_PORT}/v1/graphql"
HASURA_HEALTH_URL = f"http://{HASURA_HOST}:{HASURA_PORT}/healthz"

# Define colors for status indicators
STATUS_COLORS = {
    "connected": "🟢",
    "error": "🔴",
    "warning": "🟠",
}

# Sidebar for service selection
st.sidebar.title("Services Dashboard")

service_option = st.sidebar.radio(
    "Select Service",
    ["Overview", "Valkey", "Kafka", "Qdrant",  "PostgreSQL", "MongoDB", "Hasura"]
)


# Function to check Valkey connection
def check_valkey_connection() -> Tuple[bool, str]:
    """Check connection to Valkey server."""
    try:
        client = valkey.Valkey(host=VALKEY_HOST, port=VALKEY_PORT, socket_timeout=5)
        if client.ping():
            return True, "Connected successfully"
        return False, "Failed to ping server"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


# Function to interact with Valkey
def interact_with_valkey():
    """Display Valkey interaction UI."""
    st.title("Valkey Dashboard")

    # Connection status
    connected, message = check_valkey_connection()
    status = STATUS_COLORS["connected"] if connected else STATUS_COLORS["error"]
    st.write(f"Connection Status: {status} {message}")

    if not connected:
        st.error("Cannot connect to Valkey. Please check if the service is running.")
        return

    client = valkey.Valkey(host=VALKEY_HOST, port=VALKEY_PORT)

    # Display server info
    with st.expander("Server Information"):
        info = client.info()
        st.json(info)

    # Key management
    st.subheader("Key Management")

    col1, col2 = st.columns(2)

    with col1:
        st.write("Set a key-value pair")
        key_name = st.text_input("Key Name", "test-key")
        value = st.text_input("Value", "test-value")
        if st.button("Set Key"):
            client.set(key_name, value)
            st.success(f"Set {key_name} = {value}")

    with col2:
        st.write("Get a key value")
        get_key = st.text_input("Key to Get", "test-key")
        if st.button("Get Key"):
            val = client.get(get_key)
            if val:
                st.success(f"Value: {val.decode('utf-8')}")
            else:
                st.warning(f"Key '{get_key}' not found")

    # List all keys
    if st.button("List All Keys"):
        keys = client.keys("*")
        if keys:
            st.write("Keys in database:")
            for k in keys:
                st.write(f"- {k.decode('utf-8')}")
        else:
            st.info("No keys found in the database")


# Function to check Kafka connection
def check_kafka_connection() -> Tuple[bool, str]:
    """Check connection to Kafka broker."""
    try:
        admin_client = AdminClient({'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS})
        cluster_metadata = admin_client.list_topics(timeout=5)
        return True, f"Connected successfully. Broker count: {len(cluster_metadata.brokers)}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


# Function to interact with Kafka
def interact_with_kafka():
    """Display Kafka interaction UI."""
    st.title("Kafka Dashboard")

    # Connection status
    connected, message = check_kafka_connection()
    status = STATUS_COLORS["connected"] if connected else STATUS_COLORS["error"]
    st.write(f"Connection Status: {status} {message}")

    if not connected:
        st.error("Cannot connect to Kafka. Please check if the service is running.")
        return

    admin_client = AdminClient({'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS})

    # Topic management
    st.subheader("Topic Management")

    # List all topics
    if st.button("List All Topics"):
        try:
            topics_metadata = admin_client.list_topics(timeout=10)
            topics = list(topics_metadata.topics.keys())
            if topics:
                st.write("Available topics:")
                for topic in topics:
                    st.write(f"- {topic}")
            else:
                st.info("No topics found")
        except Exception as e:
            st.error(f"Error listing topics: {str(e)}")

    # Create a new topic
    st.write("Create a new topic")
    topic_name = st.text_input("Topic Name", "test-topic")
    num_partitions = st.number_input("Number of Partitions", min_value=1, value=1)
    replication_factor = st.number_input("Replication Factor", min_value=1, max_value=3, value=1)

    if st.button("Create Topic"):
        try:
            topic_list = [NewTopic(topic_name, num_partitions, replication_factor)]
            admin_client.create_topics(topic_list)
            st.success(f"Topic '{topic_name}' created successfully")
        except Exception as e:
            st.error(f"Error creating topic: {str(e)}")

    # Produce message
    st.subheader("Produce Message")
    prod_topic = st.text_input("Topic for Production", "test-topic")
    message_key = st.text_input("Message Key (optional)")
    message_value = st.text_area("Message Value (JSON)", "{\"message\": \"test\"}")

    if st.button("Produce Message"):
        try:
            producer = Producer({'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS})

            # Delivery callback
            def delivery_report(err, msg):
                if err is not None:
                    st.error(f'Message delivery failed: {err}')
                else:
                    st.success(f'Message delivered to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}')

            # Produce message
            producer.produce(
                prod_topic,
                key=message_key.encode('utf-8') if message_key else None,
                value=message_value.encode('utf-8'),
                callback=delivery_report
            )

            # Wait for any outstanding messages to be delivered
            producer.flush()

        except Exception as e:
            st.error(f"Error producing message: {str(e)}")

    # Consume messages
    st.subheader("Consume Messages")
    cons_topic = st.text_input("Topic for Consumption", "test-topic")
    num_messages = st.number_input("Number of Messages to Consume", min_value=1, value=5)

    if st.button("Consume Messages"):
        try:
            consumer = Consumer({
                'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
                'group.id': f'streamlit-consumer-{random.randint(1, 10000)}',
                'auto.offset.reset': 'earliest'
            })

            consumer.subscribe([cons_topic])

            messages = []
            attempts = 0

            while len(messages) < num_messages and attempts < 30:
                msg = consumer.poll(timeout=1.0)
                attempts += 1

                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        st.info(f"Reached end of partition for {cons_topic}")
                        break
                    else:
                        st.error(f"Consumer error: {msg.error()}")
                        break
                else:
                    key = msg.key().decode('utf-8') if msg.key() else "None"
                    try:
                        value = json.loads(msg.value().decode('utf-8'))
                    except:
                        value = msg.value().decode('utf-8')

                    messages.append({
                        "partition": msg.partition(),
                        "offset": msg.offset(),
                        "key": key,
                        "value": value
                    })

            consumer.close()

            if messages:
                st.write(f"Consumed {len(messages)} messages:")
                st.json(messages)
            else:
                st.info(f"No messages available in topic '{cons_topic}'")

        except Exception as e:
            st.error(f"Error consuming messages: {str(e)}")


# Function to check Qdrant connection
def check_qdrant_connection() -> Tuple[bool, str]:
    """Check connection to Qdrant server."""
    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        collections = client.get_collections().collections
        return True, f"Connected successfully. Collections: {len(collections)}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


# Function to interact with Qdrant
def interact_with_qdrant():
    """Display Qdrant interaction UI."""
    st.title("Qdrant Dashboard")

    # Connection status
    connected, message = check_qdrant_connection()
    status = STATUS_COLORS["connected"] if connected else STATUS_COLORS["error"]
    st.write(f"Connection Status: {status} {message}")

    if not connected:
        st.error("Cannot connect to Qdrant. Please check if the service is running.")
        return

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Collection management
    st.subheader("Collection Management")

    # List all collections
    if st.button("List Collections"):
        try:
            collections = client.get_collections().collections
            if collections:
                st.write("Available collections:")
                for collection in collections:
                    st.write(f"- {collection.name}")
            else:
                st.info("No collections found")
        except Exception as e:
            st.error(f"Error listing collections: {str(e)}")

    # Create a new collection
    st.write("Create a new collection")
    collection_name = st.text_input("Collection Name", "test-collection")
    vector_size = st.number_input("Vector Size", min_value=2, value=4)

    if st.button("Create Collection"):
        try:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE
                )
            )
            st.success(f"Collection '{collection_name}' created successfully")
        except Exception as e:
            st.error(f"Error creating collection: {str(e)}")

    # Upload vectors
    st.subheader("Upload Vectors")
    upload_collection = st.text_input("Collection for Upload", "test-collection")

    # Generate sample vectors
    if st.button("Generate and Upload Sample Vectors"):
        try:
            # Generate 5 sample vectors
            points = []
            for i in range(5):
                vector = [random.random() for _ in range(vector_size)]
                points.append(
                    models.PointStruct(
                        id=i,
                        vector=vector,
                        payload={"description": f"Sample vector {i}"}
                    )
                )

            # Upload vectors
            operation_info = client.upsert(
                collection_name=upload_collection,
                points=points
            )

            st.success(f"Uploaded {len(points)} vectors successfully")
            st.json({"operation_id": operation_info.operation_id})

        except Exception as e:
            st.error(f"Error uploading vectors: {str(e)}")

    # Search vectors
    st.subheader("Search Vectors")
    search_collection = st.text_input("Collection for Search", "test-collection")

    if st.button("Search with Random Vector"):
        try:
            # Generate a random query vector
            query_vector = [random.random() for _ in range(vector_size)]

            # Search
            search_result = client.search(
                collection_name=search_collection,
                query_vector=query_vector,
                limit=3
            )

            if search_result:
                st.write("Search results:")
                for result in search_result:
                    st.write(f"ID: {result.id}, Score: {result.score}")
                    st.json(result.payload)
            else:
                st.info("No search results found")

        except Exception as e:
            st.error(f"Error searching vectors: {str(e)}")


# Function to check PostgreSQL connection
def check_postgres_connection() -> Tuple[bool, str]:
    """Check connection to PostgreSQL server."""
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname=POSTGRES_DB
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return True, f"Connected successfully. {version}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


# Function to interact with PostgreSQL
def interact_with_postgres():
    """Display PostgreSQL interaction UI."""
    st.title("PostgreSQL Dashboard")

    # Connection status
    connected, message = check_postgres_connection()
    status = STATUS_COLORS["connected"] if connected else STATUS_COLORS["error"]
    st.write(f"Connection Status: {status} {message}")

    if not connected:
        st.error("Cannot connect to PostgreSQL. Please check if the service is running.")
        return

    # Create SQLAlchemy engine
    engine = create_engine(POSTGRES_URI)

    # Database management
    st.subheader("Database Management")

    # List all databases
    if st.button("List Databases"):
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT datname FROM pg_database WHERE datistemplate = false;"))
                databases = [row[0] for row in result]

                if databases:
                    st.write("Available databases:")
                    for db in databases:
                        st.write(f"- {db}")
                else:
                    st.info("No databases found")
        except Exception as e:
            st.error(f"Error listing databases: {str(e)}")

    # Table management
    st.subheader("Table Management")

    # List all tables in current database
    if st.button("List Tables"):
        try:
            with engine.connect() as conn:
                result = conn.execute(text("""
                                           SELECT tablename
                                           FROM pg_catalog.pg_tables
                                           WHERE schemaname != 'pg_catalog' 
                    AND schemaname != 'information_schema';
                                           """))
                tables = [row[0] for row in result]

                if tables:
                    st.write("Available tables:")
                    for table in tables:
                        st.write(f"- {table}")
                else:
                    st.info("No tables found in the current database")
        except Exception as e:
            st.error(f"Error listing tables: {str(e)}")

    # Create a new table
    st.write("Create a new table")
    table_name = st.text_input("Table Name", "test_table")

    if st.button("Create Test Table"):
        try:
            with engine.connect() as conn:
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100),
                        value INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """))
                conn.commit()
            st.success(f"Table '{table_name}' created successfully")
        except Exception as e:
            st.error(f"Error creating table: {str(e)}")

    # Insert data
    st.subheader("Insert Data")
    insert_table = st.text_input("Table for Insertion", "test_table")
    col1, col2 = st.columns(2)

    with col1:
        name_value = st.text_input("Name", "Test Name")

    with col2:
        number_value = st.number_input("Value", value=42)

    if st.button("Insert Row"):
        try:
            with engine.connect() as conn:
                conn.execute(
                    text(f"INSERT INTO {insert_table} (name, value) VALUES (:name, :value)"),
                    {"name": name_value, "value": number_value}
                )
                conn.commit()
            st.success(f"Data inserted into '{insert_table}' successfully")
        except Exception as e:
            st.error(f"Error inserting data: {str(e)}")

    # Query data
    st.subheader("Query Data")
    query_table = st.text_input("Table to Query", "test_table")

    if st.button("Query Table"):
        try:
            df = pd.read_sql(f"SELECT * FROM {query_table} ORDER BY id DESC LIMIT 10", engine)

            if not df.empty:
                st.write(f"Data from '{query_table}':")
                st.dataframe(df)

                # Show a simple chart if there's numeric data
                if 'value' in df.columns and not df['value'].empty:
                    fig = px.bar(df, x='name', y='value', title=f"Values from {query_table}")
                    st.plotly_chart(fig)
            else:
                st.info(f"No data found in table '{query_table}'")
        except Exception as e:
            st.error(f"Error querying data: {str(e)}")

    # Execute custom SQL
    st.subheader("Execute Custom SQL")
    sql_query = st.text_area("SQL Query", "SELECT version();")

    if st.button("Execute SQL"):
        try:
            if sql_query.lower().strip().startswith("select"):
                # For SELECT queries, show results as a dataframe
                df = pd.read_sql(sql_query, engine)
                st.write("Query results:")
                st.dataframe(df)
            else:
                # For other queries (INSERT, UPDATE, DELETE, etc.)
                with engine.connect() as conn:
                    conn.execute(text(sql_query))
                    conn.commit()
                st.success("Query executed successfully")
        except Exception as e:
            st.error(f"Error executing SQL: {str(e)}")


# Overview page
def show_overview():
    """Display overview of all services."""
    st.title("Homelab Services Overview")

    # Check connections for all services
    valkey_connected, valkey_message = check_valkey_connection()
    kafka_connected, kafka_message = check_kafka_connection()
    qdrant_connected, qdrant_message = check_qdrant_connection()
    postgres_connected, postgres_message = check_postgres_connection()
    mongodb_connected, mongodb_message = check_mongodb_connection()
    hasura_connected, hasura_message = check_hasura_connection()
    openwebui_connected, openwebui_message = check_openwebui_connection()

    # Create a DataFrame for the status table
    status_data = {
        "Service": ["Valkey", "Kafka", "Qdrant", "PostgreSQL", "MongoDB", "Hasura", "Open WebUI"],
        "Status": [
            STATUS_COLORS["connected"] if valkey_connected else STATUS_COLORS["error"],
            STATUS_COLORS["connected"] if kafka_connected else STATUS_COLORS["error"],
            STATUS_COLORS["connected"] if qdrant_connected else STATUS_COLORS["error"],
            STATUS_COLORS["connected"] if postgres_connected else STATUS_COLORS["error"],
            STATUS_COLORS["connected"] if mongodb_connected else STATUS_COLORS["error"],
            STATUS_COLORS["connected"] if hasura_connected else STATUS_COLORS["error"],
            STATUS_COLORS["connected"] if openwebui_connected else STATUS_COLORS["error"]
        ],
        "Message": [
            valkey_message,
            kafka_message,
            qdrant_message,
            postgres_message,
            mongodb_message,
            hasura_message,
            openwebui_message
        ]
    }

    status_df = pd.DataFrame(status_data)
    st.dataframe(status_df, hide_index=True, use_container_width=True)

    # Show timestamp
    st.write(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Quick access links
    st.subheader("Quick Links")
    st.markdown("""
    - **Valkey**: Redis-compatible in-memory database  
    - **Kafka**: Distributed event streaming platform  
    - **Qdrant**: Vector similarity search engine  
    - **PostgreSQL**: Advanced open-source relational database  
    - **MongoDB**: NoSQL document-oriented database  
    - **Hasura**: Instant GraphQL on PostgreSQL  
    - **Open WebUI**: Web-based user interface for managing services
    """)

    # Additional resources
    st.subheader("Additional Resources")
    cols = st.columns(7)

    with cols[0]:
        st.markdown("### Valkey")
        st.markdown("[Documentation](https://valkey.io/docs/)")

    with cols[1]:
        st.markdown("### Kafka")
        st.markdown("[Documentation](https://docs.confluent.io/platform/current/kafka/introduction.html)")

    with cols[2]:
        st.markdown("### Qdrant")
        st.markdown("[Documentation](https://qdrant.tech/documentation/)")

    with cols[3]:
        st.markdown("### PostgreSQL")
        st.markdown("[Documentation](https://www.postgresql.org/docs/17/index.html)")

    with cols[4]:
        st.markdown("### MongoDB")
        st.markdown("[Documentation](https://www.mongodb.com/docs/)")

    with cols[5]:
        st.markdown("### Hasura")
        st.markdown("[Documentation](https://hasura.io/docs/latest/)")

    with cols[6]:
        st.markdown("### Open WebUI")
        st.markdown("[Documentation](https://github.com/open-webui/open-webui)")


def check_mongodb_connection() -> Tuple[bool, str]:
    """Check connection to MongoDB server."""
    try:
        uri = f"mongodb://{MONGODB_USER}:{MONGODB_PASSWORD}@{MONGODB_HOST}:{MONGODB_PORT}/"
        client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        client.admin.command('ping')
        return True, "Connected successfully"
    except PyMongoError as e:
        return False, f"Connection error: {str(e)}"


def interact_with_mongodb():
    """Display MongoDB interaction UI."""
    st.title("MongoDB Dashboard")

    # Connection status
    connected, message = check_mongodb_connection()
    status = "🟢" if connected else "🔴"
    st.write(f"Connection Status: {status} {message}")

    if not connected:
        st.error("Cannot connect to MongoDB. Please check if the service is running.")
        return

    uri = f"mongodb://{MONGODB_USER}:{MONGODB_PASSWORD}@{MONGODB_HOST}:{MONGODB_PORT}/"
    client = MongoClient(uri)
    db = client[MONGODB_DB]

    # List collections
    if st.button("List Collections"):
        collections = db.list_collection_names()
        if collections:
            st.write("Collections:")
            for col in collections:
                st.write(f"- {col}")
        else:
            st.info("No collections found.")

    # Insert document
    st.subheader("Insert Document")
    collection_name = st.text_input("Collection Name", "test_collection")
    document_json = st.text_area("Document (JSON)", '{"name": "example", "value": 123}')

    if st.button("Insert Document"):
        try:
            doc = json.loads(document_json)
            result = db[collection_name].insert_one(doc)
            st.success(f"Inserted document with _id: {result.inserted_id}")
        except Exception as e:
            st.error(f"Error inserting document: {str(e)}")

    # Query documents
    st.subheader("Query Documents")
    query_collection = st.text_input("Collection to Query", "test_collection")
    query_json = st.text_area("Query (JSON)", '{}')
    limit = st.number_input("Limit", min_value=1, value=5)

    if st.button("Query"):
        try:
            query = json.loads(query_json)
            docs = list(db[query_collection].find(query).limit(limit))
            if docs:
                st.write("Documents:")
                st.json(docs)
            else:
                st.info("No documents found.")
        except Exception as e:
            st.error(f"Error querying documents: {str(e)}")


# Function to check Hasura connection
def check_hasura_connection() -> Tuple[bool, str]:
    """Check connection to Hasura GraphQL Engine."""
    try:
        resp = requests.get(HASURA_HEALTH_URL, timeout=3)
        if resp.status_code == 200:
            return True, "Connected successfully"
        return False, f"Healthcheck failed: {resp.status_code}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


# Function to interact with Hasura
def interact_with_hasura():
    """Display Hasura interaction UI."""
    st.title("Hasura Dashboard")

    # Connection status
    connected, message = check_hasura_connection()
    status = STATUS_COLORS["connected"] if connected else STATUS_COLORS["error"]
    st.write(f"Connection Status: {status} {message}")

    if not connected:
        st.error("Cannot connect to Hasura. Please check if the service is running.")
        return

    # GraphQL query UI
    st.subheader("GraphQL Query")
    default_query = '{\n  __schema {\n    queryType { name }\n  }\n}'
    graphql_query = st.text_area("GraphQL Query", default_query, height=150)
    variables = st.text_area("Variables (JSON)", "{}", height=68)

    if st.button("Execute GraphQL Query"):
        try:
            payload = {
                "query": graphql_query,
                "variables": json.loads(variables or '{}')
            }
            resp = requests.post(HASURA_GRAPHQL_URL, json=payload, timeout=5)
            if resp.status_code == 200:
                st.json(resp.json())
            else:
                st.error(f"Query failed: {resp.status_code} {resp.text}")
        except Exception as e:
            st.error(f"Error executing GraphQL query: {str(e)}")


def check_openwebui_connection() -> Tuple[bool, str]:
    """Check connection to Open WebUI."""
    try:
        resp = requests.get(OPENWEBUI_HEALTH_URL, timeout=3)
        if resp.status_code == 200:
            return True, "Connected successfully"
        return False, f"Healthcheck failed: {resp.status_code}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


# Main app logic
if service_option == "Overview":
    show_overview()
elif service_option == "Valkey":
    interact_with_valkey()
elif service_option == "Kafka":
    interact_with_kafka()
elif service_option == "Qdrant":
    interact_with_qdrant()
elif service_option == "PostgreSQL":
    interact_with_postgres()
elif service_option == "MongoDB":
    interact_with_mongodb()
elif service_option == "Hasura":
    interact_with_hasura()
else:
    st.warning("Please select a service from the sidebar.")