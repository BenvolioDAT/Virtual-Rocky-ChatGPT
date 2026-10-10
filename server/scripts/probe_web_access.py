"""Explicit ChatGPT-plan hosted-search integration probe; never prints tokens."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from brain.chatgpt_auth import AuthManager
from brain.chatgpt_brain import ChatGPTBrain
from brain import config

def main():
    auth=AuthManager(config._ENV_FILE.parent/'.rocky-auth')
    print(ChatGPTBrain(auth).probe_web())

if __name__=='__main__': main()
