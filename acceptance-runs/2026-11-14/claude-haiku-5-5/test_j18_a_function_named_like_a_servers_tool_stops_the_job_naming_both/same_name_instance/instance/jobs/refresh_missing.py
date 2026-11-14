async def main(job):
    result = await job.run_node("refresh", {})
    return {"returned": [result]}  # the script carries on: a node that could not go on does not fail the job
