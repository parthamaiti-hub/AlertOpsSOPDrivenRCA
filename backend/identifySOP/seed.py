import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def seed():
    from backend.sopmanagement.service import seed_all
    seed_all()


if __name__ == "__main__":
    seed()
