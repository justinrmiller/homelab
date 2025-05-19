# 🏡 Homelab Services Dashboard

A unified Streamlit dashboard for interacting with your local **Valkey**, **Kafka**, **Qdrant**, **PostgreSQL**, and **MongoDB** services.  
Easily monitor, manage, and experiment with these core open-source infrastructure tools—all from your browser.

---

## ✨ Features

- **Service Health Overview**: See live connection status for all services.
- **Valkey**: Set/get keys, list all keys, view server info.
- **Kafka**: List/create topics, produce and consume messages.
- **Qdrant**: Manage collections, upload/search vectors.
- **PostgreSQL**: List/create databases and tables, insert/query data, run custom SQL.
- **MongoDB**: List collections, insert/query documents.
- **Quick Links**: Access official documentation for each service.

---

## 🚀 Getting Started

### 🧰 Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop)
- [Docker Compose](https://docs.docker.com/compose/)
- [Python 3.8+](https://www.python.org/downloads/) (for local Streamlit development)

### 📥 Clone the Repository

```sh
git clone https://github.com/justinrmiller/homelab.git
cd homelab
```

---

## 🏃‍♂️ Running the Stack

### 1️⃣ Start All Services

```sh
docker compose up -d
```

This launches:

- Valkey
- Kafka
- Qdrant
- PostgreSQL
- MongoDB
- The Streamlit dashboard

### 2️⃣ Install Python Dependencies (for local Streamlit development)

```sh
cd streamlit
pip install -r requirements.txt
```

### 3️⃣ Run the Streamlit Dashboard

You can run the dashboard inside Docker (recommended) or locally:

**Inside Docker**:  
The dashboard will be available at [http://localhost:8501](http://localhost:8501).

**Locally**:

```sh
cd streamlit
streamlit run app.py
```

---

## ⚙️ Configuration

All service connection parameters are set via environment variables in `docker-compose.yml`.  
You can override them in your shell or with a `.env` file for local development.

**Example environment variables:**

- `VALKEY_HOST`, `VALKEY_PORT`
- `KAFKA_BOOTSTRAP_SERVERS`
- `QDRANT_HOST`, `QDRANT_PORT`
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `MONGODB_HOST`, `MONGODB_PORT`, `MONGODB_USER`, `MONGODB_PASSWORD`, `MONGODB_DB`
- `HASURA_HOST`, `HASURA_PORT`

---

## 📁 File Structure

```
homelab/
├── docker-compose.yml
├── streamlit/
│   ├── app.py
│   └── requirements.txt
└── ... (other service configs)
```

---

## 🖥️ Usage

- Open [http://localhost:8501](http://localhost:8501) in your browser.
- Use the sidebar to select a service.
- Each service page provides interactive controls for common operations.

---

## 📚 Service Documentation

- [Valkey Documentation](https://valkey.io/docs/)
- [Kafka Documentation](https://docs.confluent.io/platform/current/kafka/introduction.html)
- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/17/index.html)
- [MongoDB Documentation](https://www.mongodb.com/docs/)
- [Hasura Documentation](https://hasura.io/docs/latest/)

---

## 🛠️ Troubleshooting

- If a service is not connecting, check its logs:
  ```sh
  docker compose logs <service-name>
  ```
- Ensure ports are not in use by other processes.
- For local development, ensure your Python environment matches `requirements.txt`.

---

## 📄 License

MIT License

---

## 👤 Author

- [justinrmiller](https://github.com/justinrmiller)
- [claude](https://www.anthropic.com/claude)
