async def main(job):
    status = await job.call("tools__shell", {"command": "echo up-to-date"})
    if "up-to-date" in status["stdout"]:
        return "already current"
    await job.run_node("refresh", {"sources": "all"})
    return "refreshed"
