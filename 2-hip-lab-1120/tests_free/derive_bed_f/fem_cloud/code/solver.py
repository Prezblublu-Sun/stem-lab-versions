"""The stand-in solver: runs in the job folder, leaves a log and a "done" mark, solves nothing."""
import pathlib

pathlib.Path("solver.log").write_text("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")
pathlib.Path("done").write_text("")
