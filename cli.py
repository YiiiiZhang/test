import sys
from agent import QAOrchestrator


def main():
    print("=" * 60)
    print("QA Agent")
    print("Describe your survey request, for example:")
    print("   'I want a survey for university students about satisfaction with online learning platforms, around 10 questions.'")
    print("Type 'exit' or 'quit' to leave. You can also press Ctrl+C to force quit.")
    print("=" * 60 + "\n")

    try:
        agent = QAOrchestrator()
        print("\nAgent initialized successfully. Please describe your survey request:\n")
    except Exception as e:
        print(f"\nAgent initialization failed: {e}")
        sys.exit(1)

    while True:
        try:
            user_input = input("You: ").strip()

            if user_input.lower() in {"exit", "quit"}:
                print("Thanks for using QA Agent. Goodbye.")
                break

            if not user_input:
                continue

            print("\n" + "-" * 50)
            result = agent.run(user_input)
            print("\nAgent reply:")
            print(result)
            print("-" * 50 + "\n")

        except KeyboardInterrupt:
            print("\n\nInterrupt received. Goodbye.")
            break
        except Exception as e:
            print(f"\nAn uncaught error occurred: {e}\n")


if __name__ == "__main__":
    main()
