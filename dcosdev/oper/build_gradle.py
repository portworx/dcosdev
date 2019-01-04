template = """
group 'com.mesosphere.sdk'
version '1.1-SNAPSHOT'

apply plugin: 'java'
apply plugin: 'application'

repositories {
    jcenter()
    mavenCentral()
    maven {
        url "https://s3-us-west-1.amazonaws.com/px-dcos/maven/"
    }
    maven {
        url "https://s3-us-west-1.amazonaws.com/px-dcos/maven-snapshot/"
    }
}

ext {
    junitVer = "4.12"
    systemRulesVer = "1.16.0"
    mockitoVer = "1.9.5"
    dcosSDKVer = "0.40.5-1.3.3"

}

dependencies {
    compile "mesosphere:scheduler:${dcosSDKVer}"
    testCompile "mesosphere:testing:${dcosSDKVer}"
}

distributions {
    main {
        baseName = 'operator-scheduler'
        version = ''
    }
}

mainClassName = 'com.mesosphere.sdk.operator.scheduler.Main'
"""

