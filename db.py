import psycopg2

def get_connection():
    try:
        return psycopg2.connect(
            host="localhost",
            port=5432,
            dbname="mbti_project_db",
            user="postgres",
            password="2003200012"
        )
    except Exception as e:
        print("❌ Database connection failed:", e)
        return None
