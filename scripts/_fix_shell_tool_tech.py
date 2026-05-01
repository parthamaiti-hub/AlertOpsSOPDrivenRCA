from backend.models.database import tools_col_sync, tools_history_col_sync

r1 = tools_col_sync().update_many({"tool": "shell_script"}, {"$set": {"tool_tech": "python_script"}})
r2 = tools_history_col_sync().update_many({"tool": "shell_script"}, {"$set": {"tool_tech": "python_script"}})
print("tools:", r1.modified_count, "history:", r2.modified_count)
