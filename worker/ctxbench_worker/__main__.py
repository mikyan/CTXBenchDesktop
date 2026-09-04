import uvicorn


if __name__ == "__main__":
    uvicorn.run("ctxbench_worker.api:app", host="0.0.0.0", port=48173, access_log=False)
