import os
import subprocess

repo = os.environ['FOUNDRY_REPOSITORY'].split('/')[1]
owner = os.environ['FOUNDRY_OWNER']
env = dict(os.environ,
           FOUNDRY_SITE=f'https://{owner}.github.io',
           FOUNDRY_BASE='/'
           if repo.lower() == f'{owner.lower()}.github.io' else f'/{repo}/')
subprocess.run(['npm', 'run', 'build', '--prefix', 'website'],
               check=True,
               env=env)
