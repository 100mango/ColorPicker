/* Public-SDK synthetic capability measurement only. NOT a cleanup implementation. */
#define _DARWIN_C_SOURCE 1
#ifndef TC_PROBE_TEST
#if !defined(__APPLE__) || !defined(__MACH__) || !(defined(__arm64__) || defined(__aarch64__))
#error "Native capability requires the actual Darwin arm64 public SDK"
#endif
#define NATIVE_PUBLIC_SDK 1
#include <libproc.h>
#include <sys/proc_info.h>
#include <sys/proc.h>
#endif
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <fcntl.h>
#include <poll.h>
#ifdef TC_PROBE_TEST
#define NATIVE_PUBLIC_SDK 0
#include "tests/mock_sdk.h"
#endif

#define CAPACITY 8
#define HARD_SECONDS 12
#define CHILD_SECONDS 10
#define PHASE_SECONDS 9.0
static int stopped, first_errno, released, reaped;
static const char *reason = "not_started";
static unsigned owned_calls;
static double deadline;
static pid_t leader, descendant;
static struct proc_bsdinfo initial_leader, initial_descendant;
struct phase { int passed, count, bytes, leader_terminal, live_descendant; };
static struct phase phases[3];

/* Cancellation never initiates cleanup. Independent child alarms are already
   armed before readiness. SIGKILL of this controller also leaves only short,
   self-expiring synthetic children. No Popen/finalizer or foreign reaper exists. */
static void cancelled(int number) {
    static const char message[] = "{\"schema\":1,\"complete\":false,\"reason\":\"cancelled_or_deadline\",\"cleanup\":\"unknown_self_expiring_children\"}\n";
    (void)number;
    (void)write(STDOUT_FILENO, message, sizeof(message)-1);
    _exit(124);
}
static int arm_self_deadline(unsigned seconds) {
    struct sigaction action; memset(&action,0,sizeof(action));
    action.sa_handler=cancelled;
    if(sigemptyset(&action.sa_mask)!=0 ||
       sigaction(SIGALRM,&action,NULL)!=0 || sigaction(SIGINT,&action,NULL)!=0 || sigaction(SIGTERM,&action,NULL)!=0) return 0;
    /* Only this process's mask changes. A pending inherited cancellation may
       exit immediately here; no synthetic readiness/fork follows that exit. */
    alarm(seconds);
    sigset_t unblock;
    if(sigemptyset(&unblock)!=0 || sigaddset(&unblock,SIGALRM)!=0 ||
       sigaddset(&unblock,SIGINT)!=0 || sigaddset(&unblock,SIGTERM)!=0 ||
       sigprocmask(SIG_UNBLOCK,&unblock,NULL)!=0) return 0;
    return 1;
}
static double now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) return -1;
    return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}
static int fail(const char *why, int error) {
    if (!stopped) { stopped=1; reason=why; first_errno=error; }
    return 0;
}
static int before(void) {
    if (stopped || released) return 0;
    double t=now();
    if (t<0 || t>=deadline) return fail("deadline",0);
    return 1;
}
static int after(int error, int bad, const char *why) {
    /* errno is captured immediately. No target observation follows a denial. */
    if (error==EPERM || error==EACCES) return fail("permission_denied",error);
    if (bad || error) return fail(why,error);
    return before();
}
static int pause_briefly(void) {
    if (!before()) return 0;
    struct timespec delay={0,20000000};
    if (nanosleep(&delay,NULL)!=0) return fail("sleep_interrupted",errno);
    return before();
}
static int lease(int *terminal) {
    if (!before()) return 0;
    siginfo_t info; memset(&info,0,sizeof(info)); errno=0; owned_calls++;
    int result=waitid(P_PID,(id_t)leader,&info,WEXITED|WNOHANG|WNOWAIT);
    int error=errno;
    if (!after(error,result!=0,"waitid_failed")) return 0;
    if (info.si_pid==0) { *terminal=0; return 1; }
    if (info.si_pid!=leader || info.si_code!=CLD_EXITED || info.si_status!=0)
        return fail("unexpected_leader_status",0);
    *terminal=1; return 1;
}
static int members(pid_t ids[CAPACITY], int *count, int *bytes) {
    if (!before()) return 0;
    memset(ids,0,CAPACITY*sizeof(pid_t)); errno=0; owned_calls++;
    int size=proc_listpids(PROC_PGRP_ONLY,(uint32_t)leader,ids,CAPACITY*(int)sizeof(pid_t));
    int error=errno;
    if (!after(error,size<=0,"group_list_failed")) return 0;
    if (size>=CAPACITY*(int)sizeof(pid_t) || size%(int)sizeof(pid_t))
        return fail("uncertain_group_capacity",0);
    *count=size/(int)sizeof(pid_t); *bytes=size;
    int found=0;
    for (int i=0;i<*count;i++) {
        if (ids[i]!=leader && ids[i]!=descendant) return fail("foreign_member",0);
        if (ids[i]==leader) found++;
        for(int j=0;j<i;j++) if(ids[i]==ids[j]) return fail("duplicate_member",0);
    }
    if(found!=1) return fail("missing_held_leader",0);
    return 1;
}
static int inspect(pid_t pid, struct proc_bsdinfo *info) {
    if (!before()) return 0;
    memset(info,0,sizeof(*info)); errno=0; owned_calls++;
    int size=proc_pidinfo(pid,PROC_PIDTBSDINFO,0,info,(int)sizeof(*info));
    int error=errno;
    if (!after(error,size!=(int)sizeof(*info),"bsd_info_failed_or_short")) return 0;
    if(info->pbi_pid!=(uint32_t)pid || info->pbi_pgid!=(uint32_t)leader ||
       (info->pbi_status!=SRUN && info->pbi_status!=SSLEEP && info->pbi_status!=SZOMB) ||
       info->pbi_start_tvsec==0 || info->pbi_start_tvusec>=1000000)
        return fail("unexpected_public_fields",0);
    return 1;
}
static int same_observation(const struct proc_bsdinfo *a,const struct proc_bsdinfo *b) {
    /* Start time is a consistency check, explicitly NOT a unique lifetime ID. */
    return a->pbi_pid==b->pbi_pid && a->pbi_pgid==b->pbi_pgid &&
      a->pbi_start_tvsec==b->pbi_start_tvsec && a->pbi_start_tvusec==b->pbi_start_tvusec;
}
static int observe(int phase) {
    int terminal=0,count=0,bytes=0; pid_t ids[CAPACITY];
    struct proc_bsdinfo l,d;
    if(!lease(&terminal)) return 0;
    if(phase==1 && !terminal) return 1;
    if(!members(ids,&count,&bytes) || !inspect(leader,&l)) return 0;
    if((l.pbi_status==SZOMB)!=terminal) return fail("lease_state_disagrees",0);
    if(phase && !same_observation(&initial_leader,&l)) return fail("leader_observation_changed",0);
    int child_present=0,live=0;
    for(int i=0;i<count;i++) if(ids[i]==descendant) child_present=1;
    if(child_present) {
        if(!inspect(descendant,&d)) return 0;
        if(phase && !same_observation(&initial_descendant,&d)) return fail("descendant_observation_changed",0);
        live=d.pbi_status!=SZOMB;
    }
    phases[phase]=(struct phase){0,count,bytes,terminal,live};
    if(phase==0) {
        if(terminal || count!=2 || !live) return fail("alive_case_not_observed",0);
        initial_leader=l; initial_descendant=d; phases[0].passed=1;
    } else if(phase==1) {
        if(terminal && count==2 && live) phases[1].passed=1;
    } else if(terminal && count==1) {
        /* Synthetic children cannot spawn or rejoin: the sole descendant has
           self-exited. Recheck the exact held lease before its single reap. */
        if(!lease(&terminal)) return 0;
        if(!terminal) return fail("terminal_lease_disappeared",0);
        phases[2].passed=1;
    }
    return 1;
}
static void child_sleep_until(double limit) {
    for (;;) {
        double t=now();
        if(t<0 || t>=limit) _exit(0);
        struct timespec delay={0,20000000};
        if(nanosleep(&delay,NULL)!=0) _exit(125);
    }
}
struct ready { pid_t leader,descendant; unsigned timers_armed; };
static void synthetic_leader(int output) {
    if(!arm_self_deadline(CHILD_SECONDS)) _exit(121); /* before readiness */
    double start=now(); if(start<0 || start>=deadline || setsid()!=getpid()) _exit(121);
    int handshake[2]; if(pipe(handshake)!=0) _exit(121);
    pid_t child=fork(); if(child<0) _exit(121);
    if(child==0) {
        if(!arm_self_deadline(CHILD_SECONDS)) _exit(121); /* fork needs its own timer/mask */
        close(handshake[0]); close(output);
        close(STDIN_FILENO); close(STDOUT_FILENO); close(STDERR_FILENO);
        unsigned armed=1;
        if(write(handshake[1],&armed,sizeof(armed))!=(ssize_t)sizeof(armed)) _exit(121);
        close(handshake[1]); child_sleep_until(start+6.0<deadline ? start+6.0 : deadline);
    }
    close(handshake[1]); unsigned armed=0;
    if(read(handshake[0],&armed,sizeof(armed))!=(ssize_t)sizeof(armed) || armed!=1) _exit(121);
    close(handshake[0]); struct ready packet={getpid(),child,1};
    if(write(output,&packet,sizeof(packet))!=(ssize_t)sizeof(packet)) _exit(121);
    close(output); close(STDIN_FILENO); close(STDOUT_FILENO); close(STDERR_FILENO);
    child_sleep_until(start+2.0<deadline ? start+2.0 : deadline);
}
static void emit(int complete) {
    char buffer[4096];
    int n=snprintf(buffer,sizeof(buffer),
      "{\"schema\":1,\"complete\":%s,\"scope\":\"public_sdk_synthetic_capability_only\","
      "\"compiled_for_darwin_public_sdk\":%s,\"reason\":\"%s\",\"errno\":%d,\"owned_calls\":%u,\"leader_reaped\":%s,"
      "\"pid_bytes\":%zu,\"bsdinfo_bytes\":%zu,\"status_offset\":%zu,\"pid_offset\":%zu,"
      "\"pgid_offset\":%zu,\"start_seconds_offset\":%zu,\"start_microseconds_offset\":%zu,"
      "\"phases\":[{\"passed\":%d,\"count\":%d,\"returned_bytes\":%d,\"terminal\":%d,\"live_descendant\":%d},"
      "{\"passed\":%d,\"count\":%d,\"returned_bytes\":%d,\"terminal\":%d,\"live_descendant\":%d},"
      "{\"passed\":%d,\"count\":%d,\"returned_bytes\":%d,\"terminal\":%d,\"live_descendant\":%d}],"
      "\"general_group_oracle_proven\":false,\"unique_lifetime_identity_proven\":false}\n",
      complete?"true":"false",NATIVE_PUBLIC_SDK?"true":"false",reason,first_errno,owned_calls,reaped?"true":"false",
      sizeof(pid_t),sizeof(struct proc_bsdinfo),offsetof(struct proc_bsdinfo,pbi_status),offsetof(struct proc_bsdinfo,pbi_pid),
      offsetof(struct proc_bsdinfo,pbi_pgid),offsetof(struct proc_bsdinfo,pbi_start_tvsec),offsetof(struct proc_bsdinfo,pbi_start_tvusec),
      phases[0].passed,phases[0].count,phases[0].bytes,phases[0].leader_terminal,phases[0].live_descendant,
      phases[1].passed,phases[1].count,phases[1].bytes,phases[1].leader_terminal,phases[1].live_descendant,
      phases[2].passed,phases[2].count,phases[2].bytes,phases[2].leader_terminal,phases[2].live_descendant);
    if(n>0 && n<(int)sizeof(buffer)) (void)write(STDOUT_FILENO,buffer,(size_t)n);
}
int main(void) {
    struct sigaction old;
    if(sigaction(SIGCHLD,NULL,&old)!=0 || old.sa_handler!=SIG_DFL || (old.sa_flags&SA_NOCLDWAIT)) {
        fail("unknown_reaper_policy",errno); emit(0); return 1;
    }
    if(!arm_self_deadline(HARD_SECONDS)) {
        fail("signal_setup_failed",errno); emit(0); return 1;
    }
    double start=now(); deadline=start+PHASE_SECONDS;
    if(start<0) { fail("clock_failed",0); emit(0); return 1; }
    int channel[2]; if(pipe(channel)!=0) { fail("pipe_failed",errno); emit(0); return 1; }
    leader=fork();
    if(leader==0) { close(channel[0]); synthetic_leader(channel[1]); _exit(121); }
    if(leader<0) { fail("fork_failed",errno); emit(0); return 1; }
    close(channel[1]);
    struct pollfd waiter={channel[0],POLLIN,0};
    if(poll(&waiter,1,1000)!=1 || !(waiter.revents&POLLIN)) { fail("readiness_timeout",errno); emit(0); return 1; }
    struct ready packet;
    if(read(channel[0],&packet,sizeof(packet))!=(ssize_t)sizeof(packet) || packet.leader!=leader || packet.descendant<=0 || packet.descendant==leader || packet.timers_armed!=1) {
        fail("invalid_owned_readiness",errno); emit(0); return 1;
    }
    close(channel[0]); descendant=packet.descendant;
    if(observe(0)) for(int phase=1;phase<3 && !stopped;phase++) {
        while(!stopped && !phases[phase].passed) { if(!pause_briefly() || !observe(phase)) break; }
    }
    if(!stopped && phases[2].passed && before()) {
        int status=0; errno=0; owned_calls++;
        pid_t result=waitpid(leader,&status,WNOHANG); int error=errno;
        /* Releasing the lease closes all observation authority, even on error. */
        released=1;
        if(error==EPERM || error==EACCES) fail("permission_denied",error);
        else if(error || result!=leader || !WIFEXITED(status) || WEXITSTATUS(status)!=0) fail("exact_child_reap_failed",error);
        else { reaped=1; reason="three_synthetic_cases_observed"; }
    }
    int complete=!stopped && released && phases[0].passed && phases[1].passed && phases[2].passed;
    emit(complete); return complete?0:1;
}
