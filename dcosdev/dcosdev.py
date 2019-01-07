#!/usr/bin/env python

"""dcos service development tools.

Usage:
  dcosdev operator new <name> <sdk-version>
  dcosdev basic new <name>
  dcosdev up
  dcosdev build java
  dcosdev test <dcos-url> [--strict] [--dcos-username=<username>] [--dcos-password=<password>]
  dcosdev release <package-version> <release-version> <s3-bucket> [--universe=<universe>]
  dcosdev operator add java-scheduler
  dcosdev operator add tests
  dcosdev operator upgrade <new-sdk-version>
  dcosdev (-h | --help)
  dcosdev --version

Options:
  -h --help                   Show this screen.
  --version                   Show version.
  --universe=<universe>       Path to a clone of https://github.com/mesosphere/universe (or universe fork)
  --strict                    Test cluster is running in strict mode
  --dcos-username=<username>  dc/os username [default: bootstrapuser]
  --dcos-password=<password>  dc/os password [default: deleteme]

"""
from docopt import docopt
import os, sys, json, base64, time, datetime
from collections import OrderedDict
sys.dont_write_bytecode=True
from minio import Minio
from minio.error import ResponseError
import docker, requests
import boto3

import oper
import basic


sdk_versions = ['0.40.5-1.3.3']

def package_name():
    with open('universe/package.json', 'r') as f:
         package = json.load(f)
    return package['name']
def sdk_version():
    with open('universe/package.json', 'r') as f:
         package = json.load(f)
    return package['tags'][0]
def sha_values():
    r = requests.get('https://s3-us-west-1.amazonaws.com/px-dcos/dcos-commons/artifacts/'+sdk_version()+'/SHA256SUMS')
    #print(r)
    return {e[1]:e[0] for e in map(lambda e: e.split('  '), str(r.text).split('\n')[:-1])}

def build_repo(version='snapshot', releaseVersion=0):
    repository = {'packages': [] }
    packages = repository['packages']

    with open('universe/package.json', 'r') as f:
         package = json.load(f, object_pairs_hook=OrderedDict)
    with open('universe/config.json', 'r') as f:
         config = json.load(f, object_pairs_hook=OrderedDict)
    with open('universe/resource.json', 'r') as f:
         resource = json.load(f, object_pairs_hook=OrderedDict)
    with open('universe/marathon.json.mustache', 'r') as f:
         s = f.read()
         marathon = base64.b64encode(s%{'time_epoche_ms': str(int(time.time()*1000)), 'time_str': datetime.datetime.utcnow().isoformat()})

    if os.path.exists('java/scheduler/build/distributions/operator-scheduler.zip'):
         resource['assets']['uris']['scheduler-zip'] = 'http://minio.marathon.l4lb.thisdcos.directory:9000/artifacts/'+package_name()+'/operator-scheduler.zip'

    package['version'] = version
    package['releaseVersion'] = releaseVersion
    package['config'] = config
    package['resource'] = resource
    package['marathon'] = {"v2AppMustacheTemplate": marathon}

    packages.append(package)
    with open('universe/'+package_name()+'-repo.json', 'w') as file:
         file.write(json.dumps(repository, indent=4))

def collect_artifacts():
    artifacts = [f for f in os.listdir('.') if os.path.isfile(f)]
    artifacts.append(str('universe/'+package_name()+'-repo.json'))
    if os.path.exists('java'):
       java_projects = ['java/'+f for f in os.listdir('java') if os.path.isdir('java/'+f)]
       dists = {jp+'/build/distributions':os.listdir(jp+'/build/distributions') for jp in java_projects}
       artifacts.extend([d+'/'+f for d in dists for f in dists[d]])
    return artifacts

def upload_minio(artifacts):
    minio_host = os.environ['MINIO_HOST']
    minioClient = Minio(minio_host+':9000', access_key='minio', secret_key='minio123', secure=False)

    for a in artifacts:
        try:
           file_stat = os.stat(a)
           file_data = open(a, 'rb')
           minioClient.put_object('artifacts', package_name()+'/'+os.path.basename(a), file_data, file_stat.st_size, content_type='application/vnd.dcos.universe.repo+json;charset=utf-8;version=v4')
        except ResponseError as err:
           print(err)

def upload_aws(artifacts, bucket, package_version):
    s3 = boto3.client('s3')

    for a in artifacts:
        with open(a, "rb") as f:
             s3.upload_fileobj(f, bucket, package_name()+'/artifacts/'+package_version+'/'+os.path.basename(a), ExtraArgs={'ACL': 'public-read', 'ContentType': 'application/vnd.dcos.universe.repo+json;charset=utf-8;version=v4'})

def main():
    args = docopt(__doc__, version='dcosdev 0.0.1')
    #print(args)

    if  args['operator'] and args['new']:
        if args['<sdk-version>'] not in sdk_versions:
           print('>>> Error: unsupported sdk version! Supported sdk versions are '+str(sdk_versions)+' .')
           return

        with open('svc.yml', 'w') as file:
             file.write(oper.svc.template%{'template': args['<name>']})

        os.makedirs('universe')
        with open('universe/package.json', 'w') as file:
             file.write(oper.package.template%{'template': args['<name>'],'version': args['<sdk-version>']})
        with open('universe/marathon.json.mustache', 'w') as file:
             file.write(oper.mjm.template)
        with open('universe/config.json', 'w') as file:
             file.write(oper.config.template%{'template': args['<name>']})
        with open('universe/resource.json', 'w') as file:
             d = sha_values()
             file.write(oper.resource.template%{'template': args['<name>'],'version': args['<sdk-version>'], 'cli-darwin': d['dcos-service-cli-darwin'], 'cli-linux': d['dcos-service-cli-linux'], 'cli-win': d['dcos-service-cli.exe']})

    elif args['basic'] and args['new']:
        with open('cmd.sh', 'w') as file:
             file.write(basic.cmd.template%{'template': args['<name>']})

        os.makedirs('universe')
        with open('universe/package.json', 'w') as file:
             file.write(basic.package.template%{'template': args['<name>']})
        with open('universe/marathon.json.mustache', 'w') as file:
             file.write(basic.mjm.template)
        with open('universe/config.json', 'w') as file:
             file.write(basic.config.template%{'template': args['<name>']})
        with open('universe/resource.json', 'w') as file:
             file.write(basic.resource.template%{'template': args['<name>']})

    elif args['up']:
        build_repo()
        artifacts = collect_artifacts()
        print(">>> INFO: uploading "+str(artifacts))
        upload_minio(artifacts)
        os.remove('universe/'+package_name()+'-repo.json')
        print('\nafter 1st up: dcos package repo add '+package_name()+'-repo --index=0 http://minio.marathon.l4lb.thisdcos.directory:9000/artifacts/'+package_name()+'/'+package_name()+'-repo.json')
        print('\ndcos package install '+package_name()+' --yes')
        print('\ndcos package uninstall '+package_name())
        print('\ndcos package repo remove '+package_name()+'-repo'+'\n')

    elif args['build'] and args['java']:
        project_path =  os.environ['PROJECT_PATH'] if 'PROJECT_PATH' in os.environ else os.getcwd()
        java_projects = [f for f in os.listdir(os.getcwd()+'/java') if os.path.isdir(os.getcwd()+'/java/'+f)]
        dockerClient = docker.from_env()
        for jp in java_projects:
            print('\n>>> INFO: gradle build starting for ' + jp)
            c = dockerClient.containers.run('gradle:4.8.0-jdk8', 'gradle -s check distZip', detach=True, auto_remove=True, user='root',
                                        volumes={project_path+'/java/'+jp : {'bind': '/home/gradle/project'}}, working_dir='/home/gradle/project')
            g = c.logs(stream=True)
            for l in g:
                print(l[:-1])

    elif args['test']:
        print(">>> tests starting ...")
        project_path =  os.environ['PROJECT_PATH'] if 'PROJECT_PATH' in os.environ else os.getcwd()
        dockerClient = docker.from_env()
        c = dockerClient.containers.run('realmbgl/dcos-commons:'+sdk_version(), 'bash /build-tools/test_runner.sh /dcos-commons-dist', detach=True, auto_remove=True, working_dir='/build',
                                    volumes={project_path : {'bind': '/build'},
                                             project_path+'/tests' : {'bind': '/dcos-commons-dist/tests'},
                                             project_path+'.gradle_cache' : {'bind': '/root/.gradle'}
                                    },
                                    environment={'DCOS_ENTERPRISE': 'true',
                                                 'SECURITY': 'strict' if args['--strict'] else '',
                                                 'DCOS_LOGIN_USERNAME': args['--dcos-username'],
                                                 'DCOS_LOGIN_PASSWORD': args['--dcos-password'],
                                                 'CLUSTER_URL': args['<dcos-url>'],
                                                 'STUB_UNIVERSE_URL': 'http://'+os.environ['MINIO_HOST']+':9000/artifacts/'+package_name()+'/'+package_name()+'-repo.json',
                                                 'FRAMEWORK': package_name(),
                                                 'PYTEST_ARGS': '-m \"sanity and not azure\"'
                                    })
        g = c.logs(stream=True)
        for l in g:
            print(l[:-1])

    elif args['release']:
        build_repo(args['<package-version>'], int(args['<release-version>']))
        with open('universe/'+package_name()+'-repo.json', 'r') as f:
             repo = f.read().replace('http://minio.marathon.l4lb.thisdcos.directory:9000/artifacts/'+package_name()+'/', 'https://'+args['<s3-bucket>']+'.s3.amazonaws.com/'+package_name()+'/artifacts/'+args['<package-version>']+'/')
        with open('universe/'+package_name()+'-repo.json', 'w') as f:
             f.write(repo)
        artifacts = collect_artifacts()
        print(">>> INFO: releasing "+str(artifacts))
        upload_aws(artifacts, args['<s3-bucket>'], args['<package-version>'])

        if args['--universe']:
           path = args['--universe']+'/repo/packages/'+package_name()[0].upper()+'/'+package_name()
           if os.path.exists(path) and not os.path.exists(path+'/'+args['<release-version>']):
              path = path+'/'+str(args['<release-version>'])
              os .makedirs(path)
              with open('universe/'+package_name()+'-repo.json', 'r') as f:
                   repo = json.load(f, object_pairs_hook=OrderedDict)['packages'][0]
              with open(path+'/config.json', 'w') as f:
                   f.write(json.dumps(repo['config'], indent=4))
                   del repo['config']
              with open(path+'/resource.json', 'w') as f:
                   f.write(json.dumps(repo['resource'], indent=4))
                   del repo['resource']
              with open(path+'/marathon.json.mustache', 'w') as f:
                   base64.b64encode(repo['marathon']['v2AppMustacheTemplate'])
                   f.write(base64.b64decode(repo['marathon']['v2AppMustacheTemplate']))
                   del repo['marathon']['v2AppMustacheTemplate']
                   del repo['marathon']
              with open(path+'/package.json', 'w') as f:
                   del repo['releaseVersion']
                   f.write(json.dumps(repo, indent=4))
           else:
               print('>>> ERROR: package folder '+package_name()+ ' does not exist, or release version foler \''+args['<release-version>']+'\' exists already !')

        os.remove('universe/'+package_name()+'-repo.json')

    elif args['operator'] and args['add'] and args['java-scheduler']:
        os.makedirs('java/scheduler/src/main/java/com/mesosphere/sdk/operator/scheduler')
        with open('java/scheduler/build.gradle', 'w') as file:
             file.write(oper.build_gradle.template%{'version': sdk_version()})
        with open('java/scheduler/settings.gradle', 'w') as file:
             file.write(oper.settings_gradle.template)
        with open('java/scheduler/src/main/java/com/mesosphere/sdk/operator/scheduler/Main.java', 'w') as file:
             file.write(oper.main_java.template)

    elif args['operator'] and args['add'] and args['tests']:
        os.makedirs('tests')
        with open('tests/__init__.py', 'w') as file:
             file.write(oper.tests.init_py.template)
        with open('tests/config.py', 'w') as file:
             file.write(oper.tests.config.template%{'template': package_name()})
        with open('tests/conftest.py', 'w') as file:
             file.write(oper.tests.conftest.template)
        with open('tests/test_overlay.py', 'w') as file:
             file.write(oper.tests.test_overlay.template%{'template': package_name()})
        with open('tests/test_sanity.py', 'w') as file:
             file.write(oper.tests.test_sanity.template)

    elif args['operator'] and args['upgrade']:
        if args['<new-sdk-version>'] not in sdk_versions:
           print('>>> Error: unsupported sdk version! Supported sdk versions are '+str(sdk_versions)+' .')
           return

        old_sdk_version = sdk_version()
        print('>>> INFO: upgrade from '+old_sdk_version+' to '+args['<new-sdk-version>'])

        with open('universe/package.json', 'r') as f:
             package = f.read().replace(old_sdk_version, args['<new-sdk-version>'])
        with open('universe/package.json', 'w') as f:
             f.write(package)

        with open('universe/resource.json', 'r') as f:
             resource = f.read().replace(old_sdk_version, args['<new-sdk-version>'])
        with open('universe/resource.json', 'w') as f:
             f.write(resource)

        if os.path.exists('java/scheduler/build.gradle'):
            with open('java/scheduler/build.gradle', 'r') as f:
                 build_gradle = f.read().replace(old_sdk_version, args['<new-sdk-version>'])
            with open('java/scheduler/build.gradle', 'w') as f:
                 f.write(build_gradle)


if __name__ == '__main__':
    main()
