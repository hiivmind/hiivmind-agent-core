async def main(job):
    return {"said": await job.call("echo__say", {"text": "hello"})}
