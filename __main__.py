from invoke import Program, Collection

import setupenv
import tasks

config = {
    'run': {
        'echo': True
    },
    'NINJA_STATUS': '[%f/%t (%p) %es]'  # make the ninja output even nicer
}

ns = Collection.from_module(tasks, config=config)
ns.add_collection(Collection.from_module(setupenv, name='setup-dev-env', config=config))


class MyProgram(Program):
    pass


p = MyProgram(
    binary='m(mongodb command line tool)',
    name='MongoDB Command Line Tool',
    namespace=ns,
    version='1.0.0-alpha2')

p.run()
