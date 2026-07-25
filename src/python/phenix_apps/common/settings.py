import os

# phenix logging level. Options: ['DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL']
PHENIX_LOG_LEVEL = os.getenv("PHENIX_LOG_LEVEL", "INFO")

# Path to phenix log file
PHENIX_LOG_FILE = os.getenv("PHENIX_LOG_FILE", "/var/log/phenix/phenix-apps.log")

# Base phenix data directory
PHENIX_DIR = os.getenv("PHENIX_DIR", "/phenix")

# phenix temporary directory
PHENIX_TEMP_DIR = os.getenv("PHENIX_TEMP_DIR", "/tmp/phenix")

# Base minimega filepath
MM_FILEPATH = os.getenv("MM_FILEPATH", "/phenix/images")

# Base minimega filepath
MM_SOCKET_PATH = os.getenv("MM_SOCKET_PATH", "/tmp/minimega/minimega")

# Seconds between cc client/command polls
CC_POLL_RATE = float(os.getenv("PHENIX_CC_POLL_RATE", 2.0))

# Seconds between client-liveness checks during an unbounded cc wait
CC_LIVENESS_INTERVAL = float(os.getenv("PHENIX_CC_LIVENESS_INTERVAL", 10.0))

# Seconds to wait for a cc exit code after the response is counted
CC_EXITCODE_GRACE = float(os.getenv("PHENIX_CC_EXITCODE_GRACE", 10.0))

# Seconds to wait for a miniccc client to register
CC_CLIENT_GRACE = float(os.getenv("PHENIX_CC_CLIENT_GRACE", 300.0))

# Seconds to wait for a cc file send or component start to be acknowledged
CC_SEND_GRACE = float(os.getenv("PHENIX_CC_SEND_GRACE", 300.0))

# Seconds to wait for a cc command response. 0 == unbounded
CC_CMD_GRACE = float(os.getenv("PHENIX_CC_CMD_GRACE", 0.0))

# Seconds before the first "still waiting" log line, doubling up to the max
CC_LOG_INTERVAL = float(os.getenv("PHENIX_CC_LOG_INTERVAL", 10.0))
CC_LOG_MAX_INTERVAL = float(os.getenv("PHENIX_CC_LOG_MAX_INTERVAL", 320.0))
