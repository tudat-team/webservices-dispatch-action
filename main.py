import os
import json


def main():
    with open(os.environ["GITHUB_EVENT_PATH"], 'r') as fp:
        event_data = json.load(fp)

    print("Event data")
    print(event_data)


if __name__ == "__main__":
    main()
