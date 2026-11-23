# Post to YouTube through Zapier (one time, about 10 minutes)

The render workflow publishes the finished MP4 as a GitHub Release (this repo is public, so Zapier can
download it) and sends the title, description, tags and file link to a Zapier webhook. A Zap then
uploads it to YouTube. Zapier's YouTube app is already verified by Google, so there is no API audit
and no forced-private problem.

## 0. A separate channel
The YouTube account connected to the Zapier that Claude can see is "The Unknown Report" (the fun-facts
channel). Create a new YouTube channel for the horror manga stories, then connect THAT channel in the
Zap's YouTube step (Zapier > Connections > add YouTube, pick the new channel when Google asks).

## 1. Build the Zap
1. Trigger: **Webhooks by Zapier > Catch Hook**. Copy the Custom Webhook URL.
2. Action: **YouTube > Upload Video**, choose the new channel's connection. Map the fields:
   - Title = `title`
   - Description = `description`
   - Tags = `tags` (comma separated)
   - Video = `video_url`
   - Privacy Status = `privacy_status`
   - Made For Kids = No
   - Publish At = `publish_at` (only works for YouTube Partner accounts; leave empty otherwise)
3. First test run: the workflow sends a real payload, so run the workflow once with publish=private, then
   in the Zap click "Test trigger" and pick that sample.

## 2. Add the secret
GitHub repository > Settings > Secrets and variables > Actions > new secret
`ZAPIER_HOOK_URL` = the webhook URL.

## 3. Use it
Actions > Generate Fractured Dimension Video > Run workflow > **publish** = private (first time), unlisted
or public. The captions are already burned into the picture.
