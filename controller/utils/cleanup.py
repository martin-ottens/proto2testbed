from loguru import logger

from helper.network_helper import NetworkBridge
from state_manager import MachineState

def delete_residual_parts() -> int:
    logger.warning("This action deletes residual network interfaces and direcories of old testbed runs.")
    logger.warning("It deletes these things from ALL testbeds (even running ones) and from ALL users.")
    logger.warning("Ensure, that no one has testbeds running on this hosts before continuing.")
    response = input("Are you sure you want to continue? (yes/NO) ").strip().lower()

    if response not in ("y", "yes"):
        logger.critical("Cleanup aborted.")
        return 1

    logger.info("Deleting network bridges and tap devices ...")
    try:
        NetworkBridge.clean_all_bridges()
    except Exception as ex:
        logger.opt(exception=ex).error("Unhandled error during interface cleanup")

    logger.info("Deleting interchange direcotories ...")
    try:
        MachineState.clean_interchange_paths()
    except Exception as ex:
        logger.opt(exception=ex).error("Unhandled error during interchange directory cleanup")

    logger.success("Cleanup completed.")
    return 0
