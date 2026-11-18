async def main(job):
    result = await job.run_node("giveup", {})
    return {"returned": [result]}
