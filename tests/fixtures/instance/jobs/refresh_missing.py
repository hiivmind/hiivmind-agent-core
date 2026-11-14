async def main(job):
    result = await job.run_node("refresh", {})
    if result.get("reason") == "needs_input":
        return f"needs attention: {result['question']}"  # the script decides to carry on
    return f"refresh {result['outcome']}"
