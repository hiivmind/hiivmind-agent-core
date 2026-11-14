async def main(job):
    result = await job.run_node("giveup", {})
    return f"giveup {result['outcome']}"
