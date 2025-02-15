import uvicorn

if __name__ == "__main__":
    uvicorn.run("container_backend.asgi:application", port=3182)
