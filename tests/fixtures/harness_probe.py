"""Harmless synthetic entry point that exercises each harness capture channel."""

from pathlib import Path
import smtplib
import subprocess

import MySQLdb


connection = MySQLdb.connect(database="fixture")
cursor = connection.cursor()
cursor.execute("UPDATE fixture SET characterized=%s", (True,))
connection.commit()
cursor.close()
connection.close()

command = subprocess.run(
    ["fixture-command", "argument"],
    check=False,
    capture_output=True,
    text=True,
)
Path("artifact.txt").write_text(command.stdout, encoding="utf-8")

mailer = smtplib.SMTP("fixture-mail")
mailer.sendmail("sender@example.invalid", ["recipient@example.invalid"], "message")
mailer.quit()

print("probe complete")
