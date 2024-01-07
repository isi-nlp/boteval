/**
 * Add a message to the chat window
 * @param msgID {string} the id of the message
 * @param content {string} the content of the message, can be html
 * @param userName {string} the name of the user who sent the message
 * @param timeCreated {string} the time the message was created
 * @param color {string} the color of the message, in ["secondary", "light", "dark", "info", "primary"]
 * @param side {string} the side of the message, in ["left", "right"]
 */
function addDialogBox(msgID, content, userName, timeCreated, color, side = 'left') {
    const chat_html = `
        <li style="width:100%" id = "chat-message-${msgID}">
            <div class="card alert-${color} mb-4" style="float:${side}; width:75%">
                <div class="card-header d-flex justify-content-between p-2">
                    <p class="fw-bold mb-0"> ${userName} </p>
                    <p class="text-muted small mb-0"><i class="far fa-clock"></i>${timeCreated}</p>
                </div>
                <div class="card-body" style="padding: 0.5em">
                    ${content}
                </div>
            </div>
        </li>`
    $('#chat-thread').append($.parseHTML(chat_html))
}

/**
 * Add a message to the chat window, automatically assign color and side based on the user
 * @param msg message object, {data, user_id, time_created, text, ...}
 * @param userIDs {string[]} the IDs of all users in the chat
 * @param userRoles {string[]} the roles of all users in the chat
 * @param curUserId {string} the ID of the current user
 * @param curUserRole {string} the role of the current user, e.g. 'a', 'b', 'Moderator'...
 */
function addChatMessage(msg, userIDs, userRoles, curUserId, curUserRole) {
    const colors = ["secondary", "light", "dark", "info", "primary"]
    const userId = msg.user_id
    const idx = userIDs.indexOf(userId)
    const userRole = msg.data?.speaker_id
    const msgUserDisplayText = userId === curUserId ? `<i>Your reply as</i> ${userRole}` : userRole
    const extra = msg.data?.text_orig
    const content = msg.text
    const text_display = extra ? `
        <details>
            <summary>${content}</summary>
            <i class="text-muted">${extra}</i>
        </details>
    ` : content
    if (userRole === curUserRole) {
        // This message is from the role played by the current user
        addDialogBox(msg.id, text_display, msgUserDisplayText, msg.time_created, 'danger', 'right')
    } else {
        // The message is from the other user
        const color = (userRole === 'Moderator') ? 'success' : colors[idx % colors.length]
        addDialogBox(msg.id, text_display, msgUserDisplayText, msg.time_created, color, 'left')
    }
}

/**
 * Scroll the chat window to the bottom
 */
function scrollToBottom() {
    const chat_thread = document.getElementById('chat-thread')
    chat_thread.scrollTop = chat_thread.scrollHeight
}

/**
 * Play a sound to indicate a new message
 */
function playNewMessageSound() {
    new Audio('/static/img/new_message_beep.mp3').play();
}

/**
 * Show/Hide page elements based on the current state
 * @param state {string} in ["wait", "chat", "end"]
 */
function doSetPageState(state) {
    if (state === 'wait') {
        $('#end_info').hide()
        $('#next_msg_form').hide()  // dont let human reply
        $('#waiting_info').show()  // waiting animation show
    } else if (state === 'chat') {
        $('#end_info').hide()
        $('#next_msg_form').show() // let human reply
        $('#waiting_info').hide() // waiting animation hide
    } else if (state === 'end') {
        $('#end_info').show()
        $('#next_msg_form').hide()
        $('#waiting_info').hide()
        if (curUser.role !== 'Moderator') {
            $('#ratings-view').show()
        }
    }
}

/**
 * Refresh and put all the message on the screen
 * @param thread the chat thread json object
 */
function loadChatThreadOnScreen(thread) {
    $("#chat-thread").empty();
    const userIds = []
    const userRoles = []
    Object.keys(thread.speakers).forEach(key => {
        userIds.push(key)
        userRoles.push(thread.speakers[key])
    })
    for (const msg of thread.messages) {
        addChatMessage(msg, userIds, userRoles, curUser.id, curUser.role)
    }
    // set remaining turns
    $('#remaining-turns-count').text(thread.max_turns_per_thread - thread.current_turns)
}

const threadId = document.getElementById('thread-id').textContent;

let curUser = {
    id: document.getElementById('user-id').textContent,
    role: document.getElementById('user-role').textContent,
}

const threadFetchUrl = document.getElementById('thread-object-url').href;
const submitUrl = document.getElementById('post-message-url').href;
const botReplyUrl = document.getElementById('bot-reply-url').href;

function initChatThread() {
    fetch(threadFetchUrl)
        .then(response => response.json())
        .then(thread => {
            loadChatThreadOnScreen(thread)
            lastMessages = thread.messages.length
            scrollToBottom()
            setPageStateAccordingToThread(thread)
        })
}

let avoidDuplicateReply = false;

function tryGetBotReply(thread) {
    if (avoidDuplicateReply) {
        return
    }
    avoidDuplicateReply = true
    $.post(botReplyUrl, {
        thread_id: thread.id,
        user_id: curUser.id,
        turns: thread.current_turns,
        speaker_idx: thread.current_speaker_idx,
    }).done(reply => {
        avoidDuplicateReply = false
    }).fail(() => {
        avoidDuplicateReply = false
    })
}

/**
 * Set the page state based on the current thread state.
 * Try to get bot reply only if it's my turn next.
 * @param thread
 */
function setPageStateAccordingToThread(thread) {
    if (thread.episode_done) {
        doSetPageState('end')
        stopWaitingForNextTurn()
    } else if (thread.current_speaker === curUser.role) {
        doSetPageState('chat')
        stopWaitingForNextTurn()
    } else {
        // wait
        if (thread.need_moderator_bot && thread.current_speaker === 'Moderator') {
            const next_speaker_idx = (thread.current_speaker_idx + 1) % thread.speak_order.length
            if (thread.speak_order[next_speaker_idx] === curUser.role) {
                // it's my turn next
                tryGetBotReply(thread)
            }
        }
        doSetPageState('wait')
        startWaitingForNextTurn()
    }
}

let lastMessages = 0;

/**
 * Check if there are new messages in the thread.
 * @param thread
 */
function checkNewMessages(thread) {
    if (thread.messages.length > lastMessages) {
        lastMessages = thread.messages.length;
        playNewMessageSound()
        scrollToBottom()
    }
}

let checkThreadId = -1;

/**
 * This function is called periodically to check if current chat thread is updated or not.
 * Fetch the thread object from the server.
 * 1. It updates new messages on the screen.
 * 2. It sets the page state to 'chat', 'wait' or 'end' depending on the current turn.
 *
 */
function threadCheckHandler() {
    fetch(threadFetchUrl)
        .then(response => response.json())
        .then(thread => {
            loadChatThreadOnScreen(thread)
            checkNewMessages(thread)
            setPageStateAccordingToThread(thread)
        })
}

/**
 * Start a periodical timer to check if the thread is updated.
 * @param delay {number} the delay in seconds
 */
function startWaitingForNextTurn(delay = 5) {
    if (checkThreadId !== -1) {
        return
    }
    checkThreadId = window.setInterval(threadCheckHandler, delay * 1000)
}

/**
 * Stop the periodical.
 */
function stopWaitingForNextTurn() {
    if (checkThreadId === -1) {
        return
    }
    window.clearInterval(checkThreadId)
    checkThreadId = -1
}

function onButtonClicked(event) {
    event.preventDefault();
    const content = $("#next_msg_text").val().trim()
    if (!content) {
        return
    }
    // submit new message
    const newMessage = {
        thread_id: threadId,
        text: content,
        speaker_id: curUser.role,
        user_id: curUser.id,
    }
    $.post(submitUrl, newMessage).done(reply => {
        addDialogBox(
            reply.message_id, content, curUser.role, reply.timestamp, 'danger', 'right'
        )
        lastMessages += 1
        scrollToBottom()
        $('#next_msg_text').val('') // empty the input box
        doSetPageState('wait')
        startWaitingForNextTurn()
    }).fail(() => {
        alert('Something went wrong. Could not send message.')
    })
}


function chatUIProcess() {
    $.ajaxSetup({
        crossDomain: true,
        xhrFields: {
            withCredentials: true
        },
    });
    initChatThread()
    // submit on enter key
    $("#next_msg_text").keyup(event => {
        if (event.which === 13) {
            $("#next_msg_form").submit();
        }
    });
    $("#next_msg_form").submit(onButtonClicked);
}

window.onload = chatUIProcess;