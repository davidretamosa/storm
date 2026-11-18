"""Llança JMeter (mode -n, sense GUI) i llegeix el .jtl."""
import os
import subprocess
from pathlib import Path

import pandas as pd

DEFAULT_JMETER = Path.home() / "jmeter/apache-jmeter-5.6.3/bin/jmeter"

# El .jtl en CSV amb el que cal per a les mètriques (allThreads = fils actius de tota la prova)
JTL_PROPERTIES = {
    "jmeter.save.saveservice.output_format": "csv",
    "jmeter.save.saveservice.timestamp_format": "ms",
    "jmeter.save.saveservice.thread_counts": "true",
    "jmeter.save.saveservice.thread_name": "true",
    "jmeter.save.saveservice.label": "true",
    "jmeter.save.saveservice.response_code": "true",
    "jmeter.save.saveservice.successful": "true",
    "jmeter.save.saveservice.print_field_names": "true",
}


def jmeter_binary():
    return Path(os.environ.get("JMETER_BIN", DEFAULT_JMETER))


def run(plan, jtl, log, properties=None, jmeter=None):
    """jmeter -n -t plan -l jtl -j log -J<clau>=<valor>... ; torna el codi de sortida i la sortida."""
    command = [str(jmeter or jmeter_binary()), "-n", "-t", str(plan), "-l", str(jtl), "-j", str(log)]
    command += [f"-J{key}={value}" for key, value in (properties or {}).items()]
    command += [f"-J{key}={value}" for key, value in JTL_PROPERTIES.items()]
    result = subprocess.run(command, capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


def read_jtl(jtl):
    df = pd.read_csv(jtl)
    if df.empty:
        return df
    df["success"] = df["success"].astype(str).str.lower() == "true"
    df["responseCode"] = df["responseCode"].astype(str)
    return df
