# General Intent

When working on any project, I want to be able to test it on my current setup.

When we design something, we should start on the backend before trying to create an interface.

We should always ensure that we are not limiting our AI models or software with artificial constraints unnecessarily.

Where a responsibility can be handled reliably by deterministic software, I prefer the system to handle it there rather than making an AI model remember or infer it. AI models should be used for the cognitive work where they add value.

We should avoid designing a project around one specific AI model when that dependence is not necessary. AI models will change over time, and the surrounding system should remain usable when a model is replaced, upgraded, or assigned to a different role.

We should constantly look to see whether we should rebuild or patch a problem. Sometimes a quick patch fixes something fast, but generates many preventable problems down the road. For example, if we accidentally create something in the wrong folder or point it toward the wrong thing, sometimes it is better to move everything once than to continue trying to remember a unique path for every iteration going forward.

We should not push arbitrary work to a human when the decision can be made safely by the AI model using the proper documentation provided to it. That does not mean deciding information that can change the outcome dramatically or in irreversible ways.

If we are working in Git or GitHub, we do not want to create pathing that requires Git. Projects should be designed as downloadable packages that contain everything they require and use as few external dependencies as reasonably practical.

I prefer a techy look, but also sleek and easy to navigate. I do not want to have to click through multiple items that should be handled automatically.

Sometimes I will ask for a specific way of handling something and offer suggestions or examples. These examples should be treated as examples of the intent, not automatically as hard numbers or fixed design principles.

For instance, if I mention that I want something to run extensively and say that 20–40 hours of run time is fine, we do not have to design it to reach 20 hours. The point is that I was not expecting a fast click-it-and-be-done result; I was willing to allow it to run for an extended amount of time.

When I am chatting, I may suggest an idea. If there is a problem with the idea, I expect the AI model to point out the flaws rather than accept it as concrete law. I am learning as we go and will sometimes suggest things that are not the best option or are not even possible.

We should not limit ourselves only to what is already proven. Experimentation is how we continue to learn.

We should not decide to build an entirely new system from scratch without first checking whether a usable system already exists for our needs. Sometimes it is better to modify existing software than create new software altogether.

I am not a fan of building things twice when it is not needed. Before we build something, look and see whether we already have it. There should usually be several ways to check. Sometimes the differences justify building something new; most of the time they do not.

Prefer the simplest proven path. I want straightforward work to remain straightforward. When I already have a tool, runtime, AI model, workflow, or configuration that has worked before, the first approach should be to understand and reuse that known-working path. A new failure should not immediately be treated as evidence that the existing setup is wrong or needs to be modified. First establish what changed between the known-working case and the current one.

Unexpected complexity is a reason to reassess, not automatically a reason to build more infrastructure. If a task that should have been small begins turning into long-running diagnostics, custom tooling, new abstractions, configuration layers, validation systems, or another framework, return to the original objective and ask whether those additions are actually necessary to accomplish it. Building a new system should be an intentional goal, not something that emerges accidentally while trying to complete a simpler task.

I would rather get a small, useful result through the simplest proven route and expand only when a demonstrated need justifies it. Work already completed during an investigation can be preserved as reference, but finishing or maintaining that expanded work should not become a prerequisite unless it is genuinely required for the original goal.

When the path forward becomes difficult to explain in terms of the original objective, the work has likely drifted and should be re-anchored before continuing.

When an existing setup is known to work and we are considering changing or replacing it, preserve that known-working baseline while testing the replacement whenever practical. Prove the new path separately before destroying or substantially modifying the working one. A failed experiment should leave us with a known-good route to return to.

