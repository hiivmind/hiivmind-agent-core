async def main(job):
    result = await job.run_node("fetcher", {})  # the web server is down: this raises, and the script does not catch it
    return f"fetcher {result['outcome']}"
