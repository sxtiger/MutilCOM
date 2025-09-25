# V0.8

- add webui server, default port is: 54321

# V0.72

- add COM name, save in file 'comsetting.json'

# V0.71

- use * as a  wildcard in code_library.txt

# V0.7

- add prots set
  - file: comsettings.json
  - default : 9600,8,N,1
- add ico

# V0.6

- scan all COM ports in Computer
- use code Library to translate the COM Data code(code_library.txt)
- save the trans history(send_history.json, **auto generate**)
- save all the logs(port+data+time) per 24H with timer(log/, auto generate)

# Code_library.txt

Format: code + # + describe, Example:

```text
01 03 00 00 00 0A 44 09 #read register
```

# Dependency

```bash
pip install -r requirements.txt
```
