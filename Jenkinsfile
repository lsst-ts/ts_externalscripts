pipeline {

    agent any

    options {
      disableConcurrentBuilds()
      skipDefaultCheckout()
    }

    environment {
        network_name = "n_${env.BUILD_ID}_${env.JENKINS_NODE_COOKIE}"
        container_name = "c_${env.BUILD_ID}_${env.JENKINS_NODE_COOKIE}"
        work_branches = "${env.GIT_BRANCH} ${env.CHANGE_BRANCH} develop"
    }

    stages {
        stage ('Cloning Repos') {
            steps {
                dir(env.WORKSPACE + '/ci/ts_externalscripts') {
                    checkout scm
                }
                dir(env.WORKSPACE + '/ci/Spectractor') {
                    git branch: 'master', url: 'https://github.com/lsst-dm/Spectractor.git'
                }
                dir(env.WORKSPACE + '/ci/atmospec') {
                    git branch: 'master', url: 'https://github.com/lsst-dm/atmospec.git'
                }
                dir(env.WORKSPACE + '/ci/rapid_analysis') {
                    git branch: 'master', url: 'https://github.com/lsst-sitcom/rapid_analysis.git'
                }
                dir(env.WORKSPACE + '/ci/cwfs') {
                    git branch: 'master', url: 'https://github.com/bxin/cwfs.git'
                }
            }
        }

        stage("Pulling docker image") {
            steps {
                script {
                    sh """
                    docker pull lsstts/develop-env:develop
                    """
                }
            }
        }
        stage("Preparing environment") {
            steps {
                script {
                    sh """
                    docker network create \${network_name}
                    chmod -R a+rw \${WORKSPACE}
                    container=\$(docker run -v \${WORKSPACE}:/home/saluser/repo/ -td --rm --net \${network_name} --name \${container_name} lsstts/develop-env:develop)
                    """
                }
            }
        }
        stage("Checkout sal") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_sal && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }
        stage("Checkout salobj") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_salobj && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }
        stage("Checkout xml") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_xml && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }
        stage("Checkout IDL") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_idl && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }
        stage("Checkout ts_simactuators") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_simactuators && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }

        stage("Checkout ts_scriptqueue") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_scriptqueue && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }


        stage("Checkout ts_ATDomeTrajectory") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_ATDomeTrajectory && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }

        stage("Checkout ts_ATDome") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_ATDome && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }
        stage("Checkout ts_standardscripts") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_standardscripts && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }
        stage("Checkout ts_ATMCSSimulator") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_ATMCSSimulator && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }
        stage("Checkout ts_config_attcs") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_config_attcs && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }
        stage("Checkout ts_observatory_control") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repos/ts_observatory_control && /home/saluser/.checkout_repo.sh \${work_branches} && git pull\"
                    """
                }
            }
        }
       stage("setup Spectractor") {
           steps {
               script {
                   sh """
                   docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repo/ci/Spectractor && pip install -e . || echo FAILED to install Spectractor. Continuing...\"
                   """
               }
           }
       }
       stage("setup atmospec") {
           steps {
               script {
                   sh """
                   docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repo/ci/atmospec && eups declare -r . -t saluser && setup atmospec -t saluser && scons || echo FAILED to build atmospec. Continuing...\"
                   """
               }
           }
       }
       stage("setup rapid_analysis") {
           steps {
               script {
                   sh """
                   docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repo/ci/rapid_analysis && eups declare -r . -t saluser && setup atmospec -t saluser && setup rapid_analysis -t saluser && scons || echo FAILED to build rapid_analysis. Continuing...\"
                   """
               }
           }
       }
        stage("Build IDL files") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && make_idl_files.py --all || echo FAILED to build IDL files.\"
                    """
                }
            }
        }
        stage("Running tests") {
            steps {
                script {
                    sh """
                    docker exec -u saluser \${container_name} sh -c \"source ~/.setup.sh && cd /home/saluser/repo/ci/ts_externalscripts && eups declare -r . -t saluser && setup ts_externalscripts -t saluser && export LSST_DDS_IP=192.168.0.1 && printenv LSST_DDS_IP && py.test --junitxml=tests/.tests/junit.xml\"
                    """
                }
            }
        }
    }
    post {
        always {
            // The path of xml needed by JUnit is relative to
            // the workspace.
            junit 'ci/ts_externalscripts/tests/.tests/junit.xml'

            // Publish the HTML report
            publishHTML (target: [
                allowMissing: false,
                alwaysLinkToLastBuild: false,
                keepAll: true,
                reportDir: 'ci/ts_externalscripts/tests/.tests/',
                reportFiles: 'index.html',
                reportName: "Coverage Report"
              ])
        }
        cleanup {
            sh """
                docker exec -u root --privileged \${container_name} sh -c \"chmod -R a+rw /home/saluser/repo/ \"
                docker stop \${container_name} || echo Could not stop container
                docker network rm \${network_name} || echo Could not remove network
            """
            deleteDir()
        }
    }
}
