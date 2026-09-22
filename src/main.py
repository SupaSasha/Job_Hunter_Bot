from fastapi import FastAPI

app = FastAPI(title="Job Hunter Bot")


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
